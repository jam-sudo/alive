# CARTOGRAPHER Trust-Gate — Scientific Design Specification v2

> **상태:** K562 retrospective Trust-Gate MVP 과학 계약 확정안
> **개정일:** 2026-06-21
> **현재 범위:** Replogle K562 essential, scalar conformal error bound,
> R1+R4 PREDICT/ABSTAIN routing
> **비규범적 후속 범위:** R2/R3, causal masking, RPE1/Norman/Tahoe,
> Active Cartography

---

## 0. 문서 역할과 source-of-truth 계층

이 문서는 CARTOGRAPHER가 **과학적으로 무엇을 주장할 수 있는지**를 고정한다.

1. **Scientific claim contract:** 이 specification
2. **Execution contract:**
   `docs/superpowers/plans/2026-06-20-cartographer-mvp.md`
3. **Runtime implementation:** `src/alive/`
4. **Project-wide operational rules:** `CLAUDE.md`

위 순위는 **scientific claim 도메인**에 적용된다. Safety, seal, leakage, governance invariant는
`CLAUDE.md`(§3.1)가 최상위이며, 위 목록이 `CLAUDE.md`를 마지막에 두는 것은 claim 도메인 기준일
뿐 governance 권위를 낮추는 것이 아니다. 두 도메인이 직접 충돌하면 — 예: safety invariant가
어떤 claim 구성을 금지 — safety invariant가 우선하여 run을 중단시킨다.

문서 간 충돌이 발견되면 편리한 쪽을 임의로 선택하지 않는다. Scientific run을 중단하고
spec 또는 plan을 명시적으로 개정한 뒤 새 run ID를 만든다. 코드는 이 spec과 최신 plan에
부합해야 하며, 현재 코드의 동작이 과학 계약을 자동으로 재정의하지 않는다.

이 문서는 이전 CARTOGRAPHER 설계의 category-error, coverage-under-shift,
simulated-loop critique를 계승하지만, 현재 MVP와 후속 연구를 분리한다.

---

## 1. 한 줄 정의, 과학 질문, 비주장

### 1.1 한 줄 정의

CARTOGRAPHER Trust-Gate MVP는 frozen K562 perturbation predictor 위에서:

1. exchangeable perturbation query에 적용되는 **scalar global prediction-error bound**를
   split conformal로 보정하고,
2. perturbation-feature extrapolation(R1)과 local measured-error regression(R4)을 결합해
   **PREDICT/ABSTAIN 순서**를 생성하는 leakage-controlled 신뢰 레이어다.

`ABSTAIN`은 “이 예측의 사용을 권장하지 않는다”는 뜻이다. 현재 MVP에서는 실험을 실제로
선택하거나 수행하는 `MEASURE` action이 아니다. Acquisition은 별도 Active Cartography
protocol의 대상이다.

### 1.2 과학 질문

> Frozen additive perturbation-response predictor에 대해, R1+R4 Trust-Gate가 완전히
> held-out된 K562 perturbation의 실측 prediction error를 모든 사전등록 UQ comparator보다
> 더 잘 순위화하는가?

### 1.3 1차 endpoint

Sealed K562 evaluation에서 selective AURC를 측정한다.

```text
risk(q) = measured energy distance(predicted population, observed population)
delta_m = AURC_m - AURC_gate
```

Gate의 1차 endpoint 통과 조건은 모든 사전등록 comparator에 대한 simultaneous one-sided
family-wise 95% lower bound가 0보다 큰 것이다.

### 1.4 명시적 비주장

- Scalar error bound는 distribution-valued prediction set 또는 conformal ball이 아니다.
- Coverage 달성 자체는 routing win이 아니다.
- R4는 causal identifiability가 아니라 measured base error 위의 kNN regression이다.
- Additive ridge base는 mechanistic virtual cell이 아니다.
- K562 random perturbation split은 새로운 cell context 일반화를 검증하지 않는다.
- ABSTAIN은 정보이득 최적화 또는 실험 acquisition이 아니다.
- Synthetic fixture의 성공은 실제 K562 결과가 아니다.
- 현재 MVP는 Active Cartographer가 아니다.

---

## 2. Category-error 방어와 진짜 win

### 2.1 Coverage는 table stakes

Exchangeability가 성립하면 어떤 적절한 nonconformity score도 split conformal로 동일한
nominal marginal coverage를 얻을 수 있다. 따라서:

> “우리 방법은 90% coverage를 달성했고 baseline은 못 했다”는 CARTOGRAPHER의 win이 아니다.

현재 MVP의 conformal 산출물은 calibration error의 finite-sample quantile인 **하나의 scalar
global bound**다. 이 bound는 각 eligible K562 perturbation에 적용되지만 query마다 다른
bound가 아니며, prediction set의 크기나 모양을 비교하지 않는다.

### 2.2 AURC와 단조변환

AURC는 tie를 만들지 않는 strictly order-preserving transformation에 불변이다. 비엄격
단조변환이 tie를 만들 수 있으므로 tie-breaking 규칙은 metric implementation에서 고정한다.

`conformalized raw-distance`가 raw-distance와 동일한 순위를 보존한다면 별도 comparator
또는 별도 성과로 광고하지 않는다. Conformal error bound는 routing score가 아니다.

### 2.3 진짜 MVP win

동일 base, 동일 splits, 동일 feature access, 동일 tuning budget 아래에서 gate가 실제 error를
더 잘 순위화하는지가 유일한 헤드라인이다. Risk 축은 conformal bound나 gate score가 아니라
sealed observed population으로 계산한 oracle energy distance다.

### 2.4 Novelty의 상한

Full gate가 residual-only를 직접 이겨야 R1의 added value가 존재한다. R4 또는 supervised
error regressor가 모든 성과를 설명하면 결과는 “better error regression”이지
recoverability/identifiability novelty가 아니다.

---

## 3. 데이터와 four-way split

### 3.1 현재 dataset scope

Confirmatory MVP는 Replogle **K562 essential**만 사용한다.

RPE1, Norman, Tahoe, drug modality, combinatorial perturbation은 현재 scientific verdict에
포함하지 않는다. 이들은 §14의 별도 후속 protocol 대상이다.

### 3.2 Eligibility-before-split 계약

Split 전에 다음만으로 eligible perturbation 집합을 확정한다.

- schema-valid perturbation ID
- 등록된 최소 cell count 충족
- 명확한 external protein-sequence mapping
- primary ESM feature 생성 가능

Expression effect size, measured response strength, base error 또는 evaluation outcome을 사용한
filtering은 금지한다. 모든 exclusion reason과 ID를 manifest에 기록한다.

Feature availability를 확인하기 전에 split하거나, split 후 `feature_bank.has(id)`로 조용히
건너뛰는 scientific run은 무효다.

### 3.3 Four-way split

Perturbation ID 단위로 다음 비율을 사용한다. Cell barcode 단위 split은 금지한다.

```text
base_train              45%
method_development      25%
conformal_calibration   15%
sealed_evaluation       15%
```

- `base_train`: response transform과 base predictor fit
- `method_development`: OOF method tuning과 futility decision
- `conformal_calibration`: scalar error bound와 PREDICT threshold calibration
- `sealed_evaluation`: authorized evaluator에서 outcome을 정확히 한 번만 접근

Split은 eligible ID, registered seed, registered fractions에만 의존한다.

### 3.4 Sealed outcome 계약

Fitting API에 full oracle array를 전달하지 않는다. Outcome store는 일반 unsealed read와
`evaluate_sealed_once`를 구조적으로 분리한다.

- fit/develop/calibrate 단계의 sealed access count는 0이어야 한다.
- `FUTILITY_STOPPED`이면 sealed access는 영구히 0이다.
- Confirmatory branch는 sealed cohort를 정확히 한 번 연다.
- Access record는 materialization 전에 durable audit에 기록한다.
- Crash가 발생해도 같은 run ID로 seal을 다시 열지 않는다.

---

## 4. Perturbation feature와 response representation

### 4.1 Primary perturbation feature

Primary perturbation representation은 pinned
`esm2_t33_650M_UR50D` mean-pooled protein embedding이다.

Feature bank provenance는 최소한 다음을 포함한다.

- exact encoder model revision
- protein sequence database release
- gene↔protein ID mapping version
- mapping SHA-256
- pooling rule
- dtype와 feature dimension
- encoded feature SHA-256
- exclusion map

Feature standardization mean/scale은 usable `base_train` perturbation에만 fit한다.

### 4.2 Scientific-mode encoder 계약

Scientific run에서 config가 ESM-2를 요청하면 ESM dependency, model load 또는 GPU execution
실패는 fatal error다. Mock encoder로 자동 fallback하는 것은 금지한다.

Mock encoder는 명시적인 `synthetic`/`ci` mode에서만 허용하며, 해당 artifact는 scientific
verdict 입력으로 사용할 수 없다. Config primary encoder와 feature-bank provenance의 model
revision과 pooling이 `{model_revision}_{pooling}_pool` cross-check로 일치하지 않으면 evaluation을
거부한다. Feature dimension은 model revision에서 파생되므로 별도로 비교하지 않는다.

### 4.3 ESM batching 계약

전체 protein을 단일 batch로 처리하지 않는다.

- sequence-length bucket 사용
- config에 token budget 또는 batch size 등록
- model maximum token length 사전 검증
- 장문 sequence `error`(거부)/`truncate` policy 사전등록(현재 구현은 두 정책; window는 미구현)
- batch마다 pooled vector만 CPU로 이동
- A100 real-model smoke test 통과

장문 서열 정책 변경은 feature definition 변경이므로 새 run ID가 필요하다.

### 4.4 Response space

Controls와 `base_train` cells만 이용해 다음 transform을 fit한다.

```text
library-size normalization to 10,000
log1p
2,000 HVGs
50-dimensional PCA
```

Method-development, conformal-calibration, sealed outcome으로 HVG/PCA를 refit하거나 recenter하지
않는다. Transform state와 fit IDs를 checksum에 포함한다.

### 4.5 Equal-cell distance 계약

Primary risk는 frozen PCA space의 repeated equal-cell energy distance다.

```text
cell_cap                 96
minimum cells            64
sampling repeats          8
energy block size       256
```

Sampling은 `(run_id, perturbation ID)`에서 결정적으로 파생한다. Write-once provenance(§11.2)가
완료되어 run ID가 data-card/raw-data/sequence hash를 포함하면 sampling seed도 transitively data
checksum에 묶인다(현재 run ID는 config digest 기반).
Self-distance floor는 측정 신뢰성 진단이며 outcome-dependent exclusion에 사용하지 않는다.

---

## 5. Frozen additive base predictor

### 5.1 현재 normative base

현재 MVP base는 deep operator/OT-CFM이 아니라 additive multi-output ridge다.

```text
standardized ESM feature(phi_g)
    -> predicted PCA mean shift(phi_g @ W)
    -> transformed control population translation
```

`W`와 ridge alpha는 `base_train` 내부 CV로만 fit한다. Base는 method development 전에 freeze한다.

### 5.2 Ensemble baseline

Paired perturbation bootstrap으로 20개 additive-ridge member를 만든다. 동일 resample index를
feature와 measured outcome 양쪽에 적용한다. Ensemble disagreement는 output-space member mean
dispersion으로 계산한다.

### 5.3 현재 base의 claim 상한

Control population translation은 covariance, multimodality, cell-state-specific interaction을
새로 생성하지 못한다. 따라서 이 MVP는 conditional population-transition surrogate이며
mechanistic cell simulator 또는 full virtual cell로 주장하지 않는다.

---

## 6. Scalar conformal error bound

### 6.1 Nonconformity score

각 perturbation query의 calibration error는 다음이다.

```text
e(q) = repeated_energy_distance(base_prediction(q), observed_population(q))
```

Primary score는 frozen PCA space의 energy distance다. Sliced-Wasserstein은 보조 진단으로만
사용하며 confirmatory endpoint를 대체하지 않는다.

### 6.2 Finite-sample bound

Calibration errors 수를 `n_cal`, miscoverage를 `alpha`라 하면:

```text
k = ceil((n_cal + 1) * (1 - alpha))
error_bound = kth_order_statistic(errors, min(k, n_cal))
```

출력 명칭은 `scalar global prediction-error bound`다. `distribution ball`, `prediction set`,
`conditional guarantee`로 부르지 않는다.

### 6.3 Coverage reporting

- marginal error-bound coverage
- selective error-bound coverage
- selection coverage
- effective covered fraction
- abstain rate

모든 sealed indicator가 하나의 random calibration quantile을 공유하므로 naive Binomial
interval을 사용하지 않는다. Calibration validity는 exact split-conformal beta-binomial
predictive acceptance band로 검사한다.

Coverage failure는 `CALIBRATION_FAILURE`이며, 결과를 숨기거나 tolerance를 사후 확대하지
않는다.

---

## 7. R1+R4 Trust-Gate

### 7.1 R1 — feature extrapolation

Standardized ESM feature space에서 method-development bank까지의 mean kNN distance다.
Calibration reference를 계산할 때 self-neighbor를 leave-one-out으로 제외한다.

### 7.2 R4 — local residual regression

Feature-space kNN neighbor의 measured base error 중앙값이다. R4는 held-out error를 직접
추정하는 error-aware UQ이며 causal identifiability가 아니다.

### 7.3 Gate score

```text
gate(q) = w * ECDF(R1(q)) + (1-w) * ECDF(R4(q))
```

- `k ∈ {5, 10, 20, 40}`
- `w ∈ {0.25, 0.50, 0.75, 1.00}`
- `(k,w)`는 method-development OOF AURC로 선택
- tie: larger `w`, then smaller `k`
- `w=0`은 full gate가 아니라 residual-only comparator

PREDICT threshold는 conformal-calibration **gate scores**의 preregistered 70% quantile로 정한다.
Evaluation median 또는 evaluation outcome을 threshold에 사용하지 않는다.

### 7.4 Added-value 조건

```text
delta_added = AURC_residual_only - AURC_full_gate
```

Full gate가 residual-only보다 직접 유의하게 우수해야 R1의 added value를 인정한다. 단순히
residual-only가 다른 baseline을 이기지 못했다는 사실은 full gate의 가치를 증명하지 않는다.

---

## 8. Fair-Comparison Protocol과 comparator family

### 8.1 공정 비교 계약

모든 learned routing method는 동일한 다음 자원을 받는다.

- standardized ESM features
- method-development measured errors
- OOF folds
- registered seeds
- tuning budget
- frozen base predictions

평가 outcome을 연 뒤 comparator를 추가·삭제하거나 best baseline만 사후 선택하지 않는다.

### 8.2 사전등록 comparator

1. nearest-feature distance
2. ensemble disagreement
3. Ridge error regressor
4. gradient-boosted error regressor
5. residual-only kNN error score

Random/oracle abstention은 descriptive floor/ceiling으로만 보고하며 confirmatory comparator
family에는 포함하지 않는다.

### 8.3 OOF method development

모든 hyperparameter는 `method_development` 내부 fixed five-fold OOF AURC로 선택한다.
Registered seeds의 perturbation-level OOF score를 평균한 후 method를 lock한다.

`MethodLock`에는 전체 search table, folds, seeds, selected parameters, OOF score와 checksum을
저장한다.

---

## 9. Preregistered futility checkpoint

### 9.1 Operational status

Futility는 scientific verdict가 아니다.

```text
CONTINUE_CONFIRMATORY
FUTILITY_STOPPED
```

### 9.2 Futility statistic

Development OOF에서 `gbm_error`와 `residual_only`에 대해 계산한다.

```text
delta_m_dev = AURC_m_dev - AURC_gate_dev
```

Perturbation-level max-deviation bootstrap으로 simultaneous one-sided 90% **upper bounds**를
구한다. Normalized development risk scale에서 `delta_min = 0.01`이다.

- comparator 중 하나라도 upper bound `<= 0.01`이면 `FUTILITY_STOPPED`
- 아니면 `CONTINUE_CONFIRMATORY`

“within fold noise” 같은 육안·재량 판단은 금지한다.

### 9.3 Futility-stopped branch

- conformal artifact까지 생성 가능
- sealed access count = 0
- `scientific_verdict = null`
- empirical sealed coverage 또는 `NO_DISTINCT_WIN` 주장 금지
- 동일 run ID 영구 종료

후속 confirmatory 시도는 새 사전등록 run ID가 필요하고 stopped run을 함께 보고한다.

---

## 10. Confirmatory inference와 verdict

### 10.1 Simultaneous AURC inference

Sealed perturbation ID를 replacement bootstrap한다. 모든 method는 각 replicate에서 동일한
sampled indices를 사용한다. Comparator family 전체의 max-deviation distribution으로
simultaneous one-sided 95% lower bounds를 만든다.

모든 lower bound가 0보다 커야 primary AURC family를 통과한다.

### 10.2 Secondary AUGRC

Risk를 sealed cohort mean으로 고정 정규화하여 dimensionless AURC/AUGRC를 계산한다.

```text
AUGRC degradation = AUGRC_gate - AUGRC_comparator
```

모든 simultaneous upper bound가 preregistered margin `0.02` 이하이어야 한다.

### 10.3 Single authoritative verdict

```text
INVALID_EVALUATION
    provenance/leakage/integrity failure
    OR sealed n < 200
    OR nonfinite metric
    OR measurement-reliability precondition failure

CALIBRATION_FAILURE
    integrity valid
    BUT scalar error-bound coverage fails the registered acceptance band

GATE_WINS
    integrity valid
    AND calibration valid
    AND every simultaneous AURC lower bound > 0
    AND every AUGRC degradation upper bound <= 0.02
    AND full gate directly beats residual-only
    AND selected w > 0

NO_DISTINCT_WIN
    every other valid completed confirmatory result
```

`compute_verdict()`만 scientific verdict를 생성한다. 모든 clause와 evidence를 결과에 저장한다.

---

## 11. Provenance, immutability, scientific-run preconditions

### 11.1 필수 provenance

- raw expression data URI와 SHA-256
- protein sequence source/release와 mapping SHA-256
- eligible/excluded IDs와 이유
- manifest SHA-256
- feature-bank provenance와 SHA-256
- response-transform SHA-256
- config, lockfile, Git commit SHA-256
- MethodLock와 conformal artifact SHA-256
- sealed-access audit
- result와 report SHA-256

### 11.2 Write-once run 계약

Run ID는 config만이 아니라 data-card digest, raw-data hash, sequence-mapping hash와 함께
immutable experiment identity를 형성해야 한다.

- Existing run directory를 기본적으로 덮어쓰지 않는다.
- Resume은 모든 upstream hash가 byte-identical할 때만 허용한다.
- Stage output이 존재하면 byte-identical 재생성 외에는 거부한다.
- Ledger entry 교체를 금지하고 append-only transition을 사용한다.
- Terminal state 또는 sealed access 이후 upstream stage는 영구 잠근다.

### 11.3 2026-06-21 implementation audit에서 확인된 scientific-run blocker

다음 항목이 모두 해결되기 전에는 real K562 scientific run을 시작하지 않는다. 항목 1–5는
모두 merge되었고(아래 commit 참조), 마지막 precondition인 §4.3 A100 real-model ESM smoke
test도 2026-06-22 실하드웨어에서 통과했다. TG-K562-v1 confirmatory run은 완료되었다(§11.4).

1. ESM 초기화 실패 시 mock encoder로 silent fallback하는 경로 제거 — **해결**(commit 8b47901)
2. ESM length-bucket batching과 long-sequence policy 구현 — **해결**(commit a2f3d8f, 9f9f3aa)
3. Feature eligibility 확정 후 manifest split 생성 — **해결**(commit 8b47901)
4. Existing run directory와 ledger의 overwrite 차단 — **해결**(branch
   `cartographer-realrun-hardening`: composite run_id + prepare 재사용 거부 a040665,
   reference-bank sampling seed를 composite run_id로 통일 e50f7c8, append-only ledger +
   byte-identical-or-refuse 2146dac, terminal/seal 후 upstream stage lock 90e7f06)
5. Sequence provenance를 raw expression URI와 분리 — **해결**(commit 2dd3f65)

§4.3 A100 real-model ESM smoke test는 2026-06-22 RunPod A100 80GB에서 통과했다(실 ESM-2
650M forward, dim 1280, all-finite, GPU peak 2.71GB). 이로써 모든 real-run precondition이 충족됐다.

### 11.4 TG-K562-v1 confirmatory run 결과 (2026-06-22)

run_id `d18c601b6855b3b1` (config digest `edbeaaf0…`; data `K562_essential_raw_singlecell_01.h5ad`
figshare 20029387/files/35773219, SHA 검증; `long_sequence_policy=truncate`; eligible 1645,
split 740/411/247/247; ESM-2 t33_650M_UR50D on A100, torch 2.6.0+cu124). Mini end-to-end
validation(360 perts)와 pod leakage/provenance 100 passed 통과 후 실행. Seal 정확히 1회 개방.

**Verdict: `NO_DISTINCT_WIN`.** 등록된 verdict clause 중 `conformal_passes=true`(scalar error
bound가 sealed K562에서 유효 coverage 달성), 그러나 `aurc_family_passes=false`,
`added_value_passes=false`(full gate가 동시추론 기준에서 residual-only를 인증가능하게 못 이김),
`augrc_no_material_degradation=false`. Development OOF AURC에서도 gate(0.899)가
ensemble_disagreement(0.839)·nearest_feature(0.886)에 뒤졌다. 즉 Trust-Gate의 routing-superiority
headline은 실 K562에서 falsify되었다 — spec §2.4/§13이 사전등록한 registered negative다. Calibrated
conformal error bound는 유효하므로 보존한다.

**Provenance/무결성 검증의 한계 (overclaim 금지).** verdict가 보고하는
`integrity_valid`/`leakage_ok`/`provenance_ok`/`reliability_ok` clause는 **run 내부의 구조적
자기검증**이며 독립 audit이 아니다. '모든 무결성 검증 완료'로 표현하지 않는다 — '등록된 구조적
clause는 통과했으나 아래 한계가 있다'로 기술한다. 알려진 한계: (a) `evaluate_sealed_once`는
calibrate가 적합한 scorer artifact를 로드하지 않고 `ref_errors`에서 재적합한다 — 결정성은 통합
seed(§4.5)에 의존하며 artifact-load 검증으로 보장되지 않는다; (b) conformal scorer 결합이
암묵적이다; (c) composite run_id가 data-card의 절대경로를 그대로 bind한다(다른 mount = 다른
run_id); (d) 단일 run·단일 seed family로 독립 환경 재현이 없다; (e) off-instance 사본은 요약
artifact만 보유하며 전체 lineage는 pod `/workspace`에 있다. 결과·provenance는 immutable run dir +
off-instance 사본으로 보존한다.

### 11.5 Post-hoc OOF 진단 — 탐색적 가설 (2026-06-22, development surface only)

§11.4의 verdict는 불변이다. **아래는 다음 milestone 설계를 위한 탐색적(exploratory) 분석이며,
확정된 인과·결론이 아니다.** 개발(method_development) OOF 표면만의 read-only 진단이고 sealed
cohort는 재개방하지 않는다(§6.1). 도구: `src/alive/eval/diagnostics.py` +
`scripts/diagnose_dev_oof.py` (branch `diagnostics-oof-postmortem`). 입력: `methodlock.json`의
per-perturbation `oof_scores` + `dev_errors.npz`의 realised error (n=411). 재계산 AURC는 등록된
dev OOF AURC를 정확히 재현했다(파이프라인 sanity).

**왜 가설인가 — 검증의 한계.** 단일 post-hoc run·단일 seed family다. 상관·부분상관에
신뢰구간/유의성 검정을 부여하지 않았다(점추정만). `nearest_feature` comparator는 gate 내부 R1
component와 동일하지 않아 R1 proxy로서 불완전하다. 부분상관은 rank-선형 통제 가정에 의존한다.
dev 표면 결과라 sealed 일반화를 보장하지 않는다. 따라서 아래 수치는 방향 설정용 신호이지 입증이
아니다.

점추정 (CI 없음):
- **Spearman(score, error)**: ensemble_disagreement +0.297 > nearest_feature(R1) +0.213 >
  gate(R1⊕R4) +0.171 > residual_only(R4) +0.134 > gbm_error +0.123 > ridge_error +0.049.
- **부분 rank 상관**: `partial(feature, error | residual)` +0.193, `partial(residual, error |
  feature)` +0.097; `corr(feature, residual)` +0.192.

탐색적 가설 (세 가지, 미확정 — 다음 milestone에서 사전등록 검정으로 확인/반증 필요):

1. **Feature/서열 축(R1)이 무의미하지 않을 가능성.** nearest_feature 단독이 residual 단독보다,
   feature|residual 부분상관이 residual|feature보다 (점추정상) 크다. 이는 `added_value_passes=false`가
   'R1 무신호'가 아니라 *인증* 한계를 반영할 수 있음을 **시사**한다(확정 아님).
2. **gate의 융합이 신호를 희석할 가능성.** 결합 gate(0.171)가 nearest_feature 단독(0.213)보다
   (점추정상) 낮다 — combiner 가설.
3. **base의 ensemble disagreement가 가장 강한 신호일 가능성.** 점추정상 R1·R4·gate·supervised
   regressor를 상회 → bolt-on trust layer가 base 자체 신호에 지배될 수 있다는 가설.

탐색적 관찰: gate가 high realised error에 low/trusted score를 준 perturbation으로 HSPA9(6.94),
PHB2(5.58), INTS7, GSPT1, NLE1, ZNF236, KIF20A, CENPK, PRPF40A 등이 보였다(mito
chaperone/ribosome-biogenesis/cell-cycle 계열의 큰-효과 essential gene). 산출물:
`oof_diagnostics.json` (off-instance 사본).

**잠정 함의 (위 가설에 기반, 미확정):** (i) 서열/ESM feature를 성급히 폐기하지 않는다(가설 1).
(ii) 불확실성을 모델 *내부*(deep ensemble/posterior)에 두는 방향을 우선 검토한다(가설 3). (iii)
trust layer를 둔다면 ECDF 평균이 아니라 학습된 융합을 검토한다(가설 2). 이들은 다음 milestone의
사전등록 검정으로 확정/반증한다.

---

## 12. Reproducible execution state machine

```text
prepare
  -> fit
  -> develop
  -> futility
  -> calibrate
  -> [FUTILITY_STOPPED: report, seal remains closed]
  -> [CONTINUE_CONFIRMATORY: evaluate-once -> report]
```

### 12.1 Calibration-deliverable completion

- Tasks 1–13 및 futility report 경로 통과
- `FUTILITY_STOPPED`
- frozen config/manifest/features/base/MethodLock/conformal/provenance 존재
- sealed access 0회
- `scientific_verdict: null`

### 12.2 Confirmatory completion

- Tasks 1–17 통과
- `CONTINUE_CONFIRMATORY`
- sealed access 정확히 1회
- immutable scientific verdict와 audit report 공개
- 결과가 negative/invalid여도 삭제·대체하지 않음

---

## 13. Registered negative와 정직한 해석

### 13.1 Futility stopped

> Development evidence가 최소 relevant advantage를 지지하지 않아 confirmatory evaluation을
> 실행하지 않았다.

이는 `NO_DISTINCT_WIN`이 아니며 sealed performance에 대해 말하지 않는다.

### 13.2 Valid confirmatory negative

`NO_DISTINCT_WIN`이면:

> Scalar error calibration artifact는 유지할 수 있지만 Trust-Gate는 사전등록 comparator보다
> distinctly better한 routing을 입증하지 못했다.

### 13.3 R4가 성과를 설명

Full gate가 residual-only를 이기지 못하면 “recoverability geometry” 주장을 철회하고
error-regression 결과로 보고한다.

### 13.4 Calibration failure

Exchangeability, preprocessing, base misspecification을 새 protocol에서 조사한다. 기존
run의 tolerance를 확대하거나 result를 재분류하지 않는다.

### 13.5 Invalid evaluation

무결성 또는 reliability failure를 정확히 기록한다. 수리 후에는 새 run ID를 사용한다.

---

## 14. Deferred Research Program — 현재 MVP 비규범 범위

이 절은 현재 K562 MVP의 implementation requirement 또는 verdict 조건이 아니다.

### 14.1 R2 operator-aware identifiability

후속 deep base가 비자명한 low-rank operator `U_g V_g^T`를 학습한 경우에만 활성화한다.

```text
R2(q) = operator read-coordinate signal insufficiency
```

Activation prerequisite:

- operator-vs-bias-only base kill-gate 통과
- stable, identifiable `V_g`
- R4 ablation 상태에서 ensemble disagreement 대비 added value

Additive ridge MVP에는 R2를 소급 적용하지 않는다.

### 14.2 R3 control-context OOD

Single-context K562에서는 모든 query가 같은 control context를 공유하므로 R3는 정보가 없다.
새 cell line/context protocol에서만 사용한다.

### 14.3 Causal masking

GATE_WINS 이후 “gate가 calibration support의 인과적 함수인가”를 검사하는 후속
falsification이다.

```text
targeted pathway masking vs random placebo masking
delta_target - delta_placebo의 95% CI lower > 0
```

실패하면 recoverability 명칭을 약화하거나 conformalized-UQ/error-routing으로 재명명한다.

### 14.4 Distribution-valued prediction

Population-distribution prediction set, ball volume, heterogeneity WIN B는 별도 spec이 필요하다.
현재 scalar bound를 distribution-valued conformal set으로 재해석하지 않는다.

필수 선행조건:

- prediction-set event의 수학적 정의
- matched-event baseline
- outcome-independent heterogeneity stratum
- E-distance/SW/MMD sensitivity audit
- adequate cell and query sample size

### 14.5 Cross-context RPE1

K562→RPE1은 cell line, experimental batch, endpoint day가 함께 변하는 concept/conditional
shift다. `P(Y|X)` 불변을 전제하는 weighted conformal로 distribution-free coverage를
주장할 수 없다.

RPE1는 별도 directional external-validation protocol로만 시작하며, coverage가 아니라
applicability-domain diagnostic으로 framing한다.

### 14.6 Norman과 Tahoe

Combinatorial perturbation과 drug modality는 OOD negative control 후보이다. 현재 K562
single-gene model의 scientific verdict에 포함하지 않는다.

---

## 15. Deferred Research Program — Active Cartography

### 15.1 현재 판정

**Keep passive.** 현재 MVP의 ABSTAIN score를 곧바로 acquisition policy로 부르면 EPIG,
GO-CBED, BALD/uncertainty sampling의 재매개변수화일 가능성이 높다. Wet-lab 없는 public-oracle
replay의 최대 정직한 주장은 fixed-oracle sample-efficiency benchmark다.

### 15.2 Activation prerequisites

Active Cartography protocol은 다음을 모두 만족한 뒤 별도 spec으로 시작한다.

1. Trust-Gate MVP `GATE_WINS`
2. Full gate의 residual-only 대비 added value
3. Causal masking falsification 통과
4. Acquisition target과 uncertainty score의 구분
5. Adaptive/online conformal 또는 명시적 no-coverage claim
6. 독립적인 budgeted sealed-oracle protocol

### 15.3 필수 acquisition comparator

- random
- diversity/k-center
- pathway-stratified one-shot
- graph one-shot
- IterPert
- uncertainty-only
- conformalized EPIG
- GO-CBED-lite

### 15.4 P5 misspecification ladder

가설적 비환원 축:

> Frozen misspecified population predictor에서 recoverability-target acquisition이
> conformalized misspecified-EIG ranking보다 우수하고, 그 gap이 misspecification 증가에 따라
> 단조 확대되는가?

Misspecification ladder 후보:

- pathway masking
- operator-off under-parameterization
- HVG/PCA distortion
- K562→RPE1 concept shift

Primary measurement:

- selective AURC with oracle energy-distance risk
- effect-size-stratified hit curve
- perturbation-level simultaneous bootstrap

Hit을 “base가 틀린 query”로 정의하지 않는다. Oracle effect-size threshold를 독립적으로
사전등록한다.

Fail conditions:

- conformalized EPIG와 tie
- gap이 misspecification과 무관
- R4/error regression이 win을 전부 설명
- adaptive feedback 아래 calibration claim이 무효

하나라도 발생하면 registered negative:

> Reparameterization with no distinct active-mapping gain.

---

## 16. 보존된 historical critique decisions

다음 결정은 이전 spec에서 유지한다.

1. Coverage 자체를 novelty 또는 routing win으로 광고하지 않는다.
2. Risk 축에 conformal bound를 사용하지 않는다.
3. R4를 identifiability로 오인하지 않는다.
4. Cross-context concept shift에 distribution-free guarantee를 주장하지 않는다.
5. ABSTAIN과 information gain을 동일시하지 않는다.
6. Offline replay에서 base/calibration 갱신이 없으면 closed-loop discovery claim을 하지 않는다.
7. Outcome-defined responder stratum으로 heterogeneity win을 만들지 않는다.
8. 실패 조건과 reframe을 결과를 보기 전에 등록한다.

---

## 17. 최종 owner summary

CARTOGRAPHER Trust-Gate MVP는 K562 additive perturbation predictor 위에 두 기능만 제공한다.

1. **Scalar global conformal prediction-error bound** — calibration artifact, table stakes
2. **R1+R4 PREDICT/ABSTAIN ranking** — 모든 강한 comparator를 simultaneous inference로
   이겨야 하는 유일한 headline claim

현재 MVP의 novelty는 보장 숫자가 아니라 leakage-controlled, error-aware routing의 added
value다. Full gate가 supervised error regression과 residual-only를 이기지 못하면 정직한
negative다. R2/R3, distribution-valued sets, RPE1, causal masking, Active Cartography는 모두
별도 activation prerequisite를 가진 후속 연구이며 현재 결과에 소급해 주장하지 않는다.

모든 real-run precondition(#1–5 + §4.3 A100 ESM smoke)이 충족되어 TG-K562-v1 confirmatory
run이 2026-06-22 완료되었다(§11.4). 등록된 verdict는 `NO_DISTINCT_WIN`: conformal error
bound는 유효하나 Trust-Gate는 사전등록 comparator family를 동시추론 기준에서 인증가능하게
이기지 못했다 — 정직한 registered negative. (`added_value_passes=false`는 동시추론 인증 실패이며
'R1이 R4 위에 신호가 없다'를 뜻하지 않는다 — §11.5의 탐색적 진단은 오히려 그 반대 가설을
제기하나 미확정이다. 무결성 clause는 run 내부 구조적 자기검증으로 독립 audit이 아니다 — §11.4.)
후속 연구는 이 결과 위에서 새 mechanism을 설계하며 현재 결과에 소급해 주장하지 않는다.
