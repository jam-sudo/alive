# ALIVE — Virtual Cell Project Governance

> **문서 역할:** project-wide scientific governance and agent operating contract
> **개정일:** 2026-06-30
> **현재 활성 protocol:** `COMPOSE-K562-v1` (ACTIVE, 2026-06-30 activation; TG-K562-v1 COMPLETE) — sealed confirmatory run은 A100에서 1회
> **다음 milestone:** `COMPOSE-K562-v1` sealed double-unseen 확정 실행 → `CT-RPE1-v1` (deferred)

---

## 1. Mission

ALIVE는 단계적으로 virtual cell을 구축하는 연구 프로젝트다. 장기 목표는 perturbation과
cellular context를 입력받아 intervention 이후의 cell-population distribution을 예측하고,
예측할 수 없는 영역에서는 측정을 요청할 수 있는 causal virtual-cell world model이다.

현재 활성 MVP는 **K562 retrospective CARTOGRAPHER Trust-Gate**다. Frozen additive
perturbation-response surrogate 위에서:

1. scalar global prediction-error bound를 calibration하고,
2. held-out K562 perturbation을 PREDICT/ABSTAIN 순서로 routing한다.

현재 MVP를 mechanistic, causal, temporally resolved, clinically predictive, distribution-valued
prediction-set model 또는 Active Cartographer라고 부르지 않는다.

장기 모델 target은 다음과 같다.

$$p(X_{post}\mid P_{control}, A, C)$$

- $P_{control}$: paired individual cell이 아닌 control-cell population
- $A$: intervention 또는 CRISPRi target
- $C$: control population과 등록된 metadata에서 정의한 context
- $X_{post}$: post-intervention cell-population distribution

---

## 2. 이 문서가 규정하는 것과 규정하지 않는 것

CLAUDE.md는 다음을 규정한다.

- project-wide scientific invariants
- 현재 활성 milestone과 protocol routing
- outcome sealing과 leakage safety
- source-of-truth 우선순위
- 실험을 시작하거나 중단해야 하는 조건
- 저장소에서 작업하는 agent의 기본 행동 규칙

CLAUDE.md는 다음 세부사항을 복제하지 않는다.

- exact split fractions
- hyperparameter grids
- bootstrap replicate 수
- metric 구현 세부사항
- 함수·class 이름
- task-by-task implementation sequence

이런 항목은 versioned design spec, implementation plan, protocol과 config에서 관리한다.

---

## 3. Sources of truth

### 3.1 문서 계층

1. **Project-wide safety and governance:** `CLAUDE.md`
2. **Scientific claim contract:** 해당 milestone의 versioned design spec
3. **Execution contract:** 해당 milestone의 versioned implementation plan
4. **Exact split, thresholds, seeds and metrics:** committed protocol/config
5. **Runtime behavior:** `src/alive/`
6. **Vision and scientific principles:** `virtual-cell-model-blueprint.md`
7. **Evidence and literature:** `virtual-cell-research-report.md`
8. **Long-range milestones:** `virtual-cell-project-plan.md`

이 순위는 **도메인별**로 적용된다. Safety, seal, leakage, governance invariant는 이 문서가
최상위이고, scientific claim의 정의는 해당 milestone spec(현재 CARTOGRAPHER spec §0)이 최상위다.
Spec §0의 source-of-truth 목록은 claim 도메인 기준이라 `CLAUDE.md`를 마지막에 두지만, 이는 이
§3.1과 모순이 아니라 도메인이 다른 것이다. 두 도메인이 직접 충돌하면 — 예: safety invariant가
어떤 claim 구성을 금지 — safety invariant가 우선하여 run을 중단시키고 §3.2로 처리한다.

현재 CARTOGRAPHER protocol의 문서는 다음과 같다.

- Scientific spec:
  `docs/superpowers/specs/2026-06-20-cartographer-design.md`
- Implementation plan:
  `docs/superpowers/plans/2026-06-20-cartographer-mvp.md`
- Config:
  `configs/cartographer_trust_gate_k562_v1.yaml`

### 3.2 충돌 처리

문서가 충돌하면 조용히 해결하거나 편리한 쪽을 선택하지 않는다.

1. 모든 충돌을 보고한다.
2. Active protocol과 affected scientific invariant를 식별한다.
3. Scientific run을 시작하거나 계속하지 않는다.
4. Owner가 spec/protocol을 명시적으로 reconcile하도록 한다.
5. 변경 후 새 run identity와 artifact lineage를 만든다.

Exact split은 **명시적으로 이름 붙은 active protocol/config**가 결정한다. 이 문서의
protocol-independent safety invariant는 모든 protocol에 적용된다. Protocol-specific rule은
그 protocol이 활성화된 경우에만 적용된다.

---

## 4. Protocol registry

### 4.1 `TG-K562-v1` — COMPLETE

목적:

> K562-internal held-out perturbation에서 Trust-Gate가 모든 사전등록 UQ comparator보다
> prediction error를 더 잘 순위화하는지 검증한다.

범위:

- Replogle K562 essential single-gene CRISPRi
- one endpoint
- perturbation-ID four-way split
- K562-internal sealed evaluation
- scalar conformal error bound
- PREDICT/ABSTAIN routing
- retrospective public-data evaluation

비범위:

- RPE1 transfer claim
- new-context generalization
- mechanistic or causal virtual-cell claim
- distribution-valued prediction set
- experiment acquisition or MEASURE action

이 protocol의 exact split과 verdict는 versioned CARTOGRAPHER spec/plan/config가 결정한다.

### 4.2 `COMPOSE-K562-v1` — ACTIVE

목적:

> Norman K562 CRISPRa 조합 perturbation에서 단일-gene signature로 고정한 factor를 사용해
> transcriptome-valued 비가산 성분을 식별가능한 bilinear operator로 예측한다.

Scientific claim contract와 candidate Phase-2 config는 다음에 있다.

- Spec: `docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md`
- Candidate config: `configs/compose_k562_v1_phase2.yaml`

Owner는 Phase 2 설계와 사전등록 후보를 승인했고, 아래 6개 activation blocker가 모두
version-controlled evidence/tests로 충족되어 **2026-06-30 이 commit에서 registry를 `ACTIVE`로
전환한다**(spec §10.1). 이로써 real Phase-2 fit과 sealed outcome 접근이 인가된다. 단, 실제
sealed confirmatory run은 A100에서 유효한 `ActivationRecord`(requirement별 non-empty evidence
hash) + clean git tree로만 실행되며, COMPOSE seal은 TG-K562와 독립적으로 정확히 한 번 열린다
(§6.3). 활성화는 기존 결과에 소급 적용하지 않는다.

충족된 activation blocker (evidence: `docs/activation-evidence/compose/`, `docs/data-cards/`):

- 실제 Norman `combo_calibration` 설계행렬의 rank/conditioning evidence — `real_norman_phi_rank_report.json` (k=4/6/8 full-rank)
- adequate sample-size / detectable-effect analysis — `real_norman_detectable_effect_report.json` (double-unseen powered)
- 확정 Norman data-card와 raw-data checksum — `norman_compose_k562_v1.json`
- GEARS/CPA의 재현 가능한 dependency lock 및 실행 환경 — `gears_cpa_dependency_lock.json` (fresh-sync verified)
- 독립 COMPOSE outcome store, access audit와 write-once run lifecycle — `outcome_store.py`/`terminal.py`/`provenance2.py`
- Phase-2 implementation plan, metric known-answer tests와 leakage/integration tests — Phase-2a/2b plans + compose suite green

### 4.3 `CT-RPE1-v1` — DEFERRED NEXT MILESTONE

목적:

> K562에서 개발된 transition model 또는 trust layer가 RPE1 control context에서 shared-target
> perturbation response를 얼마나 transfer하는지 평가한다.

예상 benchmark:

```text
K562_essential perturbations + controls (day 6)  -> training/development
RPE1 controls + shared target identity (day 7)   -> inference context
RPE1 perturbed outcomes (day 7)                  -> external sealed evaluation only
```

이는 clean cell-type split이 아니다. Cell line, experiment, batch와 endpoint day가 함께
변하므로 **cross-dataset context transfer / concept shift**로 기술한다.

이 milestone은 다음이 있기 전까지 활성화하지 않는다.

- owner approval
- 별도 scientific spec과 config
- shared-target universe manifest
- RPE1-specific leakage tests
- K562 seal과 독립된 RPE1 outcome store/audit lifecycle
- adequate sample-size and detectable-effect analysis

### 4.4 Future protocols

R2/R3, causal masking, Norman/Tahoe OOD, perturbation combinations, drugs, time series,
distribution-valued prediction sets와 Active Cartography는 각각 별도 이름·spec·seal·success
criteria가 필요한 후속 protocol이다.

---

## 5. Universal scientific invariants

1. **Protocol first.** Training, tuning 또는 evaluation 전에 active protocol, manifest, primary
   metric, comparator family, failure conditions를 version-control한다.
2. **Baseline first.** Learned model의 성과를 보기 전에 registered baselines와 evaluation
   harness를 구현한다.
3. **Seal evaluation outcomes.** Active protocol의 evaluation outcome은 model/method selection이
   freeze된 뒤 authorized evaluation code에서만 접근한다.
4. **Fit on training roles only.** Normalization, feature selection, embeddings, calibration,
   hyperparameters와 thresholds는 protocol이 허용한 role만 사용한다.
5. **No outcome-selected test set.** Evaluation target universe는 metadata, external-feature
   availability와 사전등록 QC로 결정한다. Response strength나 base error로 고르지 않는다.
6. **Split at the claim unit.** Perturbation-level claim은 perturbation ID로 split한다. Cell
   barcode split으로 unseen-perturbation claim을 만들지 않는다.
7. **Match claim to split.** K562-internal split은 new-context transfer를 증명하지 않는다.
   Shared-target K562→RPE1 split은 unseen-target generalization을 증명하지 않는다.
8. **Risk is measured outcome error.** Routing utility를 conformal bound, confidence score 또는
   자기 자신의 threshold로 평가하지 않는다.
9. **Coverage is table stakes.** Calibration validity 자체를 routing novelty로 광고하지 않는다.
10. **No single-metric win.** Primary metric, registered secondary metrics, effect sizes,
    perturbation-level confidence intervals와 failed runs를 모두 보고한다.
11. **Interrogate systematic variation.** Batch, cell cycle, target-panel bias, common treatment
    shifts와 mean collapse를 점검한다.
12. **Do not overclaim heterogeneity.** Responder/non-responder 또는 multimodality는
    outcome-independent operational definition과 noise audit 없이 주장하지 않는다.
13. **Uncertainty needs a method.** Raw variance를 aleatoric/epistemic uncertainty로 부르지
    않는다. Estimator, calibration role과 coverage event를 명시한다.
14. **Negative results are results.** Futility, calibration failure, invalid evaluation과
    no-distinct-win 결과를 삭제·대체하거나 threshold를 사후 변경하지 않는다.

---

## 6. Protocol-specific seal contracts

### 6.1 `TG-K562-v1` seal

- Eligible K562 perturbation ID를 먼저 확정한 후 four-way split한다.
- `base_train`, `method_development`, `conformal_calibration`, `sealed_evaluation` 역할은 서로
  disjoint하다.
- Fit/develop/calibrate 단계의 K562 sealed access count는 0이어야 한다.
- Futility-stopped run은 sealed access count 0으로 영구 종료한다.
- Confirmatory branch만 K562 sealed outcome을 정확히 한 번 연다.
- K562 sealed run을 열었다고 RPE1 seal이 열린 것은 아니다.

### 6.2 `CT-RPE1-v1` seal

이 규칙은 CT-RPE1 protocol이 명시적으로 활성화된 경우에만 적용된다.

- RPE1 controls는 inference context로 사용할 수 있다.
- RPE1 perturbed outcomes는 model selection freeze 후 evaluation code만 열 수 있다.
- Normalization, feature selection, calibration, threshold와 tuning은 RPE1 perturbed outcome을
  사용할 수 없다. Protocol이 허용한 control-only context transform은 예외다.
- Scored target universe는 K562↔RPE1 shared targets와 metadata/QC로 사전 정의한다.
- RPE1 response strength로 null/weak/strong target을 선택하지 않는다.
- RPE1 outcome audit는 TG-K562 audit와 별도 저장·검증한다.
- K562-internal 결과를 RPE1 external validation으로 표현하지 않는다.

### 6.3 Multiple-seal rule

서로 다른 protocol의 seal은 대체 가능하지 않다. 하나의 run ID, audit file 또는 result가
K562-internal seal과 RPE1 external seal을 동시에 대표할 수 없다. Cross-protocol comparison은
각 protocol의 immutable artifact를 입력으로 받는 별도 analysis여야 한다.

---

## 7. Data governance

- Source family: versioned Replogle et al. processed Perturb-seq AnnData
- Standard container: AnnData (`.h5ad`)
- Raw counts와 provenance metadata 보존
- Sparse/on-disk/chunked access 사용
- Bounded population/minibatch만 densify
- Dataset asset, day, endpoint와 target universe를 manifest에 기록
- `K562_gwps`를 `K562_essential` 대신 조용히 사용하지 않음
- Cell-count/UMI threshold를 universal fact로 hardcode하지 않음
- 실제 분포를 profile하고 threshold와 sensitivity를 사전등록
- Raw/processed data, checkpoints, credentials와 identifiable donor data를 commit하지 않음
- Large transfer 전 size, destination, license 확인

External perturbation feature eligibility는 split 전에 확정한다. Missing/ambiguous sequence를
split 후 조용히 건너뛰지 않는다.

---

## 8. Model and feature governance

### 8.1 Current K562 Trust-Gate

현재 TG-K562 base는 ESM target feature와 additive population-shift predictor를 사용한다.
정확한 architecture와 grid는 CARTOGRAPHER spec/config가 정한다.

Scientific mode에서:

- requested ESM encoder 실패를 mock encoder로 조용히 대체하지 않는다.
- Mock features는 synthetic/CI artifact로만 사용한다.
- Feature-bank model revision, dimension, pooling과 config를 대조한다.
- ESM은 bounded token-budget batches로 실행한다.
- Long-sequence policy와 sequence database release를 기록한다.

### 8.2 Future transition models

Deep encoder, low-rank operator, OT-CFM, NB decoder 또는 other virtual-cell architecture는 별도
model spec과 baseline/ablation이 필요하다. 현재 additive base의 결과를 deep virtual-cell
성과로 표현하지 않는다.

### 8.3 Distribution claims

Population samples를 출력한다고 자동으로 heterogeneity를 학습한 것은 아니다. Pseudobulk,
means, self-distance floor와 mean-collapse diagnostics를 유지한다.

---

## 9. Baseline governance

모든 protocol은 strongest eligible baseline과 비교한다. Baseline roster는 evaluation outcome을
보기 전에 고정한다.

### 9.1 `TG-K562-v1`

현재 comparator family는 CARTOGRAPHER spec/config에 등록한다. 최소한 다음 범주를 포함한다.

- feature-distance UQ
- ensemble-disagreement UQ
- linear supervised error regression
- nonlinear supervised error regression
- gate component ablation

Gate가 comparator family 전체를 simultaneous inference로 이겨야 success를 주장한다.

### 9.2 `CT-RPE1-v1`

활성화 시 최소한 다음을 포함한다.

1. no-change / RPE1-control prediction
2. transferred K562 perturbation effect or perturbation-mean baseline
3. additive or latent-additive baseline
4. linear ID-only baseline

Biological gene/pathway/network encoder는 ID-only baseline과 ablation한다. Shared-target transfer
결과를 unseen-target generalization으로 표현하지 않는다.

---

## 10. Evaluation and success governance

- Versioned evaluation protocol을 model comparison 전에 freeze한다.
- Primary metric의 방향과 scientific event를 명시한다.
- Toy data에서 known-answer metric tests를 갖는다.
- Strongest comparator를 evaluation에서 사후 선택해 ordinary pairwise CI를 적용하지 않는다.
- Comparator family selection을 반영한 simultaneous inference를 사용한다.
- Secondary biological/distributional metric의 material-regression margin을 사전등록한다.
- Per-target results, null/weak behavior, seed variability, self-prediction/noise ceilings와 failed
  runs를 보고한다.
- Independent prospective hit-rate validation은 별도 milestone이다.

Futility status와 scientific verdict를 혼합하지 않는다. Development-only stop은 sealed
performance에 대한 negative verdict가 아니다.

---

## 11. Run identity, provenance and immutability

모든 run은 다음을 기록한다.

- active protocol name/version
- resolved config
- dataset/data-card hash
- manifest and exclusion hash
- feature-bank and sequence-mapping hash
- seed
- Git SHA
- dependency lock hash
- device and precision
- stage artifacts and checksums
- seal access audit
- result/report checksum

Run directory와 ledger는 write-once state machine이어야 한다.

- Existing run을 조용히 덮어쓰지 않는다.
- Resume은 upstream hashes가 byte-identical할 때만 허용한다.
- Ledger entry를 새 checksum으로 교체하지 않는다.
- Terminal status 또는 seal access 후 upstream stage를 재실행하지 않는다.
- Input lineage가 달라지면 새 run identity를 사용한다.

---

## 12. Repository conventions

```text
src/alive/data/         ingestion, manifest, preprocessing, feature bank, outcome store
src/alive/base/         frozen base predictors
src/alive/gate/         Trust-Gate components
src/alive/baselines/    registered UQ/error baselines
src/alive/conformal/    scalar calibration artifacts
src/alive/metrics/      distance and selective metrics
src/alive/eval/         bootstrap, verdict, reports
src/alive/experiment/   staged development and evaluation
configs/                immutable experiment configurations
tests/                  unit, leakage, metric, reproducibility, integration
docs/                   versioned specs, plans and audits
artifacts/              gitignored immutable run outputs
```

- Python version은 `pyproject.toml`을 따른다.
- Public API에 type hints와 NumPy-style docstrings를 사용한다.
- Ruff line length 100과 committed lockfile을 사용한다.
- Hardcoded paths, split IDs, thresholds, feature lists, seeds와 hyperparameters를 production
  source에 넣지 않는다.
- Production logic은 `src/`에 두고 notebooks는 library function만 호출한다.
- 명령을 추측하지 않는다. `pyproject.toml`, CLI help와 README를 확인한다.

---

## 13. Verification before completion

관련 변경마다:

1. targeted unit tests 실행
2. applicable integration tests 실행
3. Ruff lint/format 실행
4. data/evaluation 변경 시 leakage tests 실행
5. metric 변경 시 known-answer, constant, shuffled, random sanity 실행
6. artifact/provenance 변경 시 tamper and resume tests 실행
7. 실행한 명령, 결과, skip과 완료하지 못한 검사를 보고

Scientific run 전에는 active spec/plan/config와 runtime behavior의 contract audit를 수행한다.
문서와 코드가 충돌하면 테스트가 통과해도 run을 시작하지 않는다.

---

## 14. Compute and execution environments

### 14.1 MacBook Pro — Phase 0 and mini validation

- Apple M5 Pro, 24 GB unified memory, macOS/arm64
- Local CUDA 없음
- Repository setup, implementation, unit tests, bounded inspection, CPU/MPS smoke tests,
  mini-dataset end-to-end, documentation과 reproducibility checks에 사용
- Full source dataset을 기본적으로 MacBook에 두지 않음
- Mini fixture는 CPU에서도 실행 가능한 크기로 유지
- Device fallback을 숨기지 않음

### 14.2 Rented A100 — Phase 1 and full-data execution

- Original-data acquisition, integrity check, slicing, preprocessing, mini creation, real ESM
  feature generation과 full-data execution에 사용
- 별도 CPU-only cloud instance를 요구하지 않음
- Mini와 full은 동일 production code를 사용하고 config만 scale/device를 변경
- Mini pipeline의 leakage, metric, provenance, resume/report 검증 후 full run 시작
- Cloud run은 instance/GPU, image/lock, input hashes, Git SHA, config, wall time과 cost 기록
- Ephemeral disk를 artifact의 유일한 사본으로 사용하지 않음

`CT-RPE1-v1` mini dataset을 만들 때만 shared K562↔RPE1 targets와 RPE1 seal roles를 보존한다.
현재 `TG-K562-v1` mini는 K562 four-way roles를 보존한다.

---

## 15. Working style

- Inspect before editing.
- Scientifically consequential change 전 affected invariants와 protocol을 먼저 식별한다.
- Unrelated user changes를 보존한다.
- Established protocol을 조용히 rewrite하지 않는다.
- 현재 hypothesis를 falsify할 수 있는 가장 작은 실험을 선호한다.
- 좋은 결과일수록 leakage, batch confounding, mean collapse, metric gaming과 seed sensitivity를
  먼저 검사한다.
- Evidence level과 uncertainty를 명시한다.
- Preprint, vendor 또는 model-generated claim을 ground truth로 취급하지 않는다.
- 규칙이 타당한 작업을 막으면 우회하지 말고 충돌을 보고한다.

---

## 16. Current governance summary

```text
COMPLETE:
  TG-K562-v1
  K562 internal four-way split
  K562 sealed evaluation
  scalar error calibration + Trust-Gate routing

ACTIVE (2026-06-30 activation):
  COMPOSE-K562-v1
  Norman K562 CRISPRa pair-level split
  independent COMPOSE seal (activated; opens once — A100 sealed run pending)

DEFERRED:
  CT-RPE1-v1
  K562 -> RPE1 shared-target context transfer
  independent RPE1 external seal

RULE:
  Protocol seals, claims, manifests, run IDs and reports are never interchangeable.
```

현재 active scientific protocol은 `COMPOSE-K562-v1`이다(2026-06-30 activation, spec §10.1의 6개
blocker 충족). real Phase-2 fit과 sealed outcome 접근이 인가됐으나, 실제 sealed confirmatory run은
A100에서 유효한 `ActivationRecord` + clean git tree로만 실행되고 COMPOSE seal은 정확히 한 번
열린다. RPE1 perturbed outcomes 접근은 여전히 별도 protocol(`CT-RPE1-v1`) 활성화를 요구한다.
