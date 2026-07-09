# CARTOGRAPHER MVP 수정안 및 Active Cartographer 가능성 평가

> **⚠ SUPERSEDED (2026-07-04) — 2026-06-21 시점 검토.** 이 개정 제안서 이후 `TG-K562-v1`은 COMPLETE
> (sealed verdict `NO_DISTINCT_WIN`)이 됐고 활성 protocol은 `COMPOSE-K562-v1`(ACTIVE 2026-06-30)이다.
> 현재 상태는 `CLAUDE.md` §5 registry. 원본은 기록으로 보존한다.

작성일: 2026-06-21  
대상 문서: `docs/superpowers/plans/2026-06-20-cartographer-mvp.md`  
주의: 이 문서는 원본 계획을 수정하지 않은 독립적인 검토·개정 제안서다.

---

## 1. 요약 결론

### 1.1 현재 CARTOGRAPHER MVP 계획

현재 계획은 소프트웨어 모듈화와 테스트 설계는 좋지만, 실제로 구현되는 것은 **Active
Cartographer가 아니라 post-hoc selective-prediction trust gate**다. 또한 실제 K562 decisive
experiment가 없고 synthetic test가 gate의 승리를 검증하지 않으므로, 현재 상태로는 계획의 첫
문장에 제시된 과학적 질문에 답할 수 없다.

권장 명칭은 다음과 같다.

> **CARTOGRAPHER Trust-Gate MVP**

이 단계는 폐기할 대상이 아니라 Active Cartographer의 안전 계층으로 유지할 가치가 있다.

### 1.2 Active Cartographer의 가능성

Active Cartographer는 정의에 따라 가능성이 달라진다.

| 정의 | 판정 | 근거 |
|---|---|---|
| 기존 데이터에서 숨긴 perturbation을 순차 공개하는 retrospective simulation | **현재 가능** | IterPert 등 선행 연구와 완전한 Perturb-seq pool 존재 |
| 새 cell context에서 소수 seed를 이용해 나머지 반응을 복원 | **연구적으로 가능** | MapPFN·HyperMap이 context-conditioned/few-shot mapping 가능성을 보임 |
| 모델이 다음 seed를 선택해 random·one-shot보다 실험 수를 줄임 | **가능하지만 미확정** | active design의 양성 결과와 cold-start 실패 결과가 모두 존재 |
| 실제 wet-lab과 여러 차례 순환하는 prospective system | **기술적으로 가능하나 현재 자원 범위 밖** | 각 실험 round의 시간·비용과 실험 파트너 필요 |
| K562/RPE1 두 screen만으로 범용 causal cellular map 학습 | **현재 불가능에 가까움** | context 수 부족, batch·day confounding, transcriptome의 비식별성 |

따라서 “Active Cartographer는 non-feasible”이라는 포괄적 판단은 지나치게 강하다. 정확한 결론은
다음과 같다.

> **Retrospective, budgeted, context-adaptive Active Cartographer는 feasible하다. 범용 causal
> cartographer는 현재 데이터로 feasible하지 않다.**

---

## 2. Active Cartographer의 운영 정의

새로운 context (c)에서 control population과 지금까지 관찰한 anchor 실험을 다음처럼 둔다.

\[
D_t^c=\{(a_i,Y_{a_i}^c)\}_{i=1}^{K_t}
\]

- (a_i): 이미 측정한 anchor perturbation
- (Y_{a_i}^c): 해당 context에서 측정한 post-perturbation population
- (K_t): 현재까지 소비한 실험 예산

예측기는 아직 측정하지 않은 query perturbation (a_q)의 분포를 추정한다.

\[
\hat p(Y_{a_q}^c\mid P_{control}^c,D_t^c,a_q)
\]

Acquisition policy는 다음 실험을 선택한다.

\[
a_{t+1}=\arg\max_{a\in U_t}
\left[
\mathbb E\{\operatorname{MapError}(M_t)-\operatorname{MapError}(M_{t+1})\}
-\lambda\operatorname{Cost}(a)
\right]
\]

실제 구현에서는 예상 map-error 감소를 직접 계산하기 어려우므로 다음 대리 목적을 사용할 수 있다.

```text
acquisition(a)
  = uncertainty(a)
  × novelty_or_diversity(a)
  × pathway_coverage_gain(a)
  × estimated_learnability(a)
```

여기서 Trust Gate는 단순히 PREDICT/ABSTAIN만 수행하지 않고 세 가지 행동을 결정하는 것이 더
Cartographer다운 구조다.

```text
PREDICT  — 이미 충분히 신뢰 가능
MEASURE  — 불확실하지만 관측하면 지도를 크게 개선할 수 있음
ABSTAIN  — 현재 표현·데이터로 회복 가능성이 낮음
```

이 **PREDICT / MEASURE / ABSTAIN** 정책이 일반적인 active learning과 차별화될 수 있는 핵심이다.

---

## 3. 선행 연구가 보여주는 가능성

### 3.1 Sequential Perturb-seq design은 이미 계산적으로 실증됐다

IterPert는 multimodal prior와 순차적 실험 설계를 사용해 다음 perturbation을 선택한다. 저자들은
일부 설정에서 다음으로 좋은 방법보다 약 3분의 1 수준의 perturbation으로 비슷한 정확도에
도달했다고 보고했다. 코드도 공개되어 있다.

- [RECOMB 2024 논문](https://doi.org/10.1007/978-1-0716-3989-4_2)
- [공개 코드](https://github.com/Genentech/iterative-perturb-seq)

PerTurboAgent 역시 축적된 결과, pathway 분석 및 외부 지식을 이용해 순차 Perturb-seq panel을
선택한다. 이는 실험 선택 루프 자체가 계산적으로 성립함을 보여준다.

- [PerTurboAgent preprint](https://doi.org/10.1101/2025.05.25.656020)

### 3.2 새 context를 몇 개의 seed로 보정하는 모델도 등장했다

MapPFN은 observational population과 소수의 interventional context를 입력으로 받아 새로운
perturbation distribution을 in-context learning으로 예측한다. synthetic causal prior만으로
사전학습한 모델이 실제 single-cell 데이터로 전이되는 결과를 보고했다.

- [MapPFN](https://arxiv.org/abs/2601.21092)

HyperMap은 reference perturbation atlas를 새로운 context로 옮길 때 소수의 perturbation seed를
사용한다. iPSC donor, 다른 cell line, 약물 및 일부 새로운 knockdown으로 확장한 결과를 보고한다.

- [HyperMap](https://sciety.org/articles/activity/10.64898/2026.04.23.720505)

이 두 연구는 Active Cartographer의 predictor 부분, 즉 **anchor를 받으면 새 context map을
업데이트하는 능력**이 원리적으로 가능함을 뒷받침한다.

### 3.3 그러나 active selection이 항상 이기는 것은 아니다

Active learning은 초기 모델이 부정확할 때 잘못된 perturbation을 연속 선택할 수 있다. 한 연구는
Perturb-seq에서 제한된 round와 initialization bias 때문에 graph-based one-shot selection이 active
learning과 비슷하거나 더 안정적일 수 있다고 보고했다. 특히 prior-only selection이 강력한 경우도
있었다.

- [Efficient Data Selection for Training Genomic Perturbation Models](https://arxiv.org/abs/2503.14571)

따라서 Active Cartographer의 정당한 비교 상대는 random만이 아니다.

```text
random
diversity / k-center
pathway-stratified one-shot
GraphReach / MaxSpec류 one-shot
IterPert류 sequential active
uncertainty-only
hybrid warm-start + active
oracle upper bound
```

가장 현실적인 전략은 **one-shot diverse warm start 후 active acquisition으로 전환하는 hybrid**다.

---

## 4. 현재 ALIVE 데이터에서 가능한 것과 불가능한 것

### 4.1 가능한 retrospective 실험

Replogle essential screens는 K562 약 2,057 targets, RPE1 약 2,393 targets를 포함한다. 보고된
median cells/perturbation은 각각 약 121과 72다.

- [Perturb-seq 데이터 특성 분석](https://pmc.ncbi.nlm.nih.gov/articles/PMC11244993/)

따라서 다음 retrospective simulation은 가능하다.

```text
K562_essential outcomes                  → reference atlas / pretraining
RPE1 controls                            → new-context basal state
RPE1 acquisition pool outcomes           → anchor를 선택할 때만 순차 공개
RPE1 sealed audit outcomes               → 모든 round에서 비공개 평가
```

### 4.2 주의해야 할 한계

1. K562와 RPE1은 cell identity뿐 아니라 experiment와 endpoint day도 다르다.
2. RPE1은 perturbation당 세포 수가 적어 population distance의 sampling noise가 크다.
3. 두 context만으로 context-selection policy의 보편적 일반화를 주장할 수 없다.
4. retrospective 공개는 실제 prospective 실험의 delay, failure 및 batch drift를 모사하지 못한다.
5. transcriptome endpoint만으로 causal mechanism이나 true identifiability를 증명할 수 없다.

Systema는 perturbation benchmark가 systematic variation과 평균 treatment shift에 의해 과대평가될
수 있음을 보였다. 따라서 map error는 반드시 perturbation-specific reference와 단순 baseline을 함께
사용해 평가해야 한다.

- [Systema](https://www.nature.com/articles/s41587-025-02777-8)

또한 복잡한 perturbation model이 단순 linear·mean baseline을 일관되게 이기지 못한다는 결과가
있으므로 predictor와 acquisition 모두 강한 단순 기준선과 비교해야 한다.

- [Nature Methods 2025](https://www.nature.com/articles/s41592-025-02772-6.pdf)

---

## 5. Feasibility를 판정하는 단계별 Kill Gate

Active selection부터 구현하면 predictor failure와 acquisition failure를 구분할 수 없다. 다음 순서를
권장한다.

### Gate A — Passive few-shot benefit

질문:

> 무작위로 주어진 (K)개 RPE1 anchor가 K=0 zero-shot보다 sealed audit map을 개선하는가?

비교 예산:

```text
K = 0, 1, 2, 4, 8, 16, 32
```

판정:

- 여러 split/seed에서 map error 감소
- perturbation-level bootstrap CI
- identity/mean collapse가 아닌 perturbation-specific 개선

Gate A가 실패하면 active selection은 의미가 없다. 모델이 anchor evidence를 활용하지 못하기
때문이다.

### Gate B — One-shot seed quality

질문:

> pathway/diversity 기반 warm-start가 random seed보다 좋은가?

이는 active round의 cold-start 위험을 줄이고, 순차 실험이 필요한지 판단하는 기준점이 된다.

### Gate C — Active acquisition benefit

질문:

> 같은 누적 예산에서 active policy가 best random·one-shot·IterPert류 baseline보다 learning curve를
> 개선하는가?

주요 지표:

- Area Under Learning Curve
- 목표 error에 도달하는 데 필요한 anchor 수
- 각 (K)에서 sealed-audit perturbation-specific error
- uncertainty calibration
- pathway/feature-space coverage

### Gate D — Cross-context replication

RPE1 한 context에서만 성공하면 dataset-specific result다. 추가 donor·cell line·drug atlas 중 최소 한
곳에서 방향을 재현해야 “context-adaptive cartographer”로 주장할 수 있다.

### Gate E — Prospective validation

실제 wet-lab에서 모델이 선택한 작은 panel을 수행해 random 또는 expert panel보다 정보 획득 효율이
높은지 검증한다. 이것은 장기 단계이며 현재 MVP의 필수 성공 조건은 아니다.

---

## 6. CARTOGRAPHER Trust-Gate MVP 수정안

### 6.1 목표 교체

현재 목표 문장을 다음처럼 바꾼다.

```md
**Goal:** Determine whether a calibrated, error-aware trust gate ranks real
held-out K562 perturbation errors better than distance-only, ensemble-only,
and supervised error-prediction baselines.

The primary endpoint is improvement in selective AURC on a sealed real-data
evaluation split. Synthetic experiments validate implementation only and
cannot produce the scientific verdict.
```

### 6.2 Real-data split contract

```text
K562 perturbations
├── base-train        base predictor 학습
├── gate-calibration  gate·conformal·threshold 보정
└── sealed-evaluation 최종 AURC와 CI
```

- 분할 단위는 perturbation이다.
- Split manifest는 사전에 고정한다.
- Base는 train만 사용한다.
- Gate, score normalization, conformal radius와 decision threshold는 calibration에서 고정한다.
- Evaluation outcome은 최종 runner에서만 접근한다.
- Outcome-dependent target filtering을 금지한다.

### 6.3 Coverage 정의 분리

```python
marginal_set_coverage = covered.mean()
selective_set_coverage = covered[predict].mean()
selection_coverage = predict.mean()
effective_covered_fraction = (covered & predict).mean()
abstain_rate = 1.0 - selection_coverage
```

두 coverage 목표를 별도 config로 둔다.

```text
1 - alpha                  conformal prediction-set coverage
target_selection_coverage  PREDICT 비율
```

Decision threshold는 evaluation median이 아니라 calibration quantile에서 결정한다.

```python
threshold = np.quantile(cal_gate_scores, target_selection_coverage)
```

### 6.4 Fair-Comparison Protocol 보강

Gate가 calibration oracle error를 사용하므로 supervised error baseline이 필수다.

1. raw feature distance
2. ensemble disagreement
3. kNN residual predictor
4. ridge residual predictor
5. gradient-boosted error predictor
6. gate without residual component
7. full gate

핵심 비교는 다음이다.

```text
full gate vs strongest eligible supervised error-prediction baseline
```

K562 단일 context에서는 control population이 모든 query에서 같으므로 Control-OOD 축은 비활성화하거나
정보량이 0임을 명시한다.

### 6.5 Bootstrap 부호 통일

양수일수록 gate의 개선으로 정의한다.

\[
\Delta=\operatorname{AURC}_{baseline}-\operatorname{AURC}_{gate}
\]

```python
win = ci_low > 0
```

Strongest baseline은 calibration에서 사전 선택하거나 각 bootstrap replicate에서 다시 선택한다.

### 6.6 Synthetic test 수정

Generator가 recoverability label을 반환하도록 한다.

```python
queries, oracle, is_recoverable = make_synthetic_queries(...)
```

Recoverability는 관측 가능한 feature/context 구조와 연결한다. 생성 후 shuffle하여 train/cal/eval로
나눈다.

Positive fixture:

```python
assert out["verdict"] == "GATE_WINS"
assert out["ci_improvement"]["low"] > 0
```

Negative fixture:

```python
assert out["verdict"] == "NO_DISTINCT_WIN"
```

현재처럼 두 verdict를 모두 허용하는 assertion은 제거한다.

### 6.7 Ensemble bootstrap pairing 수정

각 member마다 동일한 index를 query와 target에 사용한다.

```python
members = []
for _ in range(n_members):
    idx = rng.integers(0, len(tr_q), size=bootstrap_size)
    members.append(
        AdditiveBase.fit(
            [tr_q[j] for j in idx],
            [tr_o[j] for j in idx],
            ridge=ridge,
        )
    )
```

### 6.8 Gate 계산 수정

- Calibration query 자신을 kNN bank에서 제외한다.
- 실제 density-relative score가 아니라면 이름을 `knn_feature_distance`로 바꾼다.
- Control OOD normalization은 원점 norm이 아니라 leave-one-out control-distance 분포를 사용한다.
- Feature/context block을 별도로 정규화하고 가중 결합한다.
- Min-max scaling보다 calibration empirical CDF를 사용한다.
- Full gate가 residual-only baseline보다 나은지 ablation한다.

### 6.9 Replogle loader 수정

다음을 금지한다.

```python
X = np.asarray(a.X)
hash(gene)
random placeholder features in a scientific run
```

다음 구조를 권장한다.

```python
dataset = load_replogle(path, schema_config)
queries = build_queries(dataset, split_manifest, feature_bank, transform)
```

요구사항:

- sparse matrix 유지
- 실제 obs schema 검증
- control label을 config로 명시
- stable external gene-feature table 사용
- train-only expression transform
- control population 중복 저장 방지
- dataset checksum과 provenance 기록

### 6.10 실제 decisive experiment 작업 추가

#### Task 12 — Real preprocessing and split manifest

```text
artifacts/data/
├── target_manifest.csv
├── split_manifest.csv
├── preprocessing.json
├── feature_bank.npz
└── checksums.sha256
```

#### Task 13 — Fit real base and calibration methods

- base-train에서 predictor와 ensemble 학습
- calibration에서 supervised error baselines와 gate 학습
- radius와 threshold 고정
- 모든 artifact 저장

#### Task 14 — Sealed real K562 evaluation

```text
results/cartographer-trust-gate/
├── metrics.json
├── per_target.csv
├── risk_coverage.png
├── bootstrap_differences.npy
├── resolved_config.yaml
├── split_hash.txt
└── report.md
```

이 작업만 scientific verdict를 생성할 수 있다.

### 6.11 Trust-Gate 성공 기준

```md
CARTOGRAPHER Trust Gate wins only if:

1. The sealed real K562 evaluation completes without leakage.
2. Marginal conformal coverage is within its preregistered tolerance.
3. AURC improvement over the strongest eligible supervised baseline has
   perturbation-bootstrap 95% CI lower bound > 0.
4. No preregistered material degradation occurs on secondary risk metrics.
5. The improvement is not carried solely by the local-residual component.
6. Results reproduce across registered seeds and split sensitivity analyses.
```

Verdict는 세 종류로 둔다.

```text
GATE_WINS
NO_DISTINCT_WIN
INVALID_EVALUATION
```

---

## 7. Active Cartographer 권장 실험 설계

### 7.1 Dataset partition

RPE1 target universe를 episode마다 다음처럼 분리한다.

```text
warm-start pool   one-shot seed 후보
acquisition pool  active policy가 선택할 수 있는 후보
sealed audit set  어떤 round에서도 outcome 비공개
```

Pathway family 또는 gene module 단위 split도 함께 수행해 가까운 paralog·동일 pathway 누출을
점검한다.

### 7.2 Episode

```text
1. K562 atlas와 RPE1 control을 제공한다.
2. Warm-start policy가 K0 anchors를 선택한다.
3. 선택된 RPE1 outcomes만 공개한다.
4. Predictor/context adapter를 업데이트한다.
5. Acquisition policy가 다음 batch를 선택한다.
6. Sealed audit set의 map error를 측정한다.
7. 예산이 끝날 때까지 반복한다.
```

모든 정책은 동일한 초기 pool, batch size, 총예산, predictor 및 audit set을 사용한다.

### 7.3 Acquisition baselines

- random
- gene-feature k-center
- pathway-stratified coverage
- graph one-shot selection
- uncertainty-only
- expected-model-change 또는 expected-map-error reduction
- IterPert류 prior-guided acquisition
- Trust-Gate 기반 hybrid
- oracle upper bound

### 7.4 Primary endpoint

\[
\operatorname{AULC}=\sum_K w_K\operatorname{MapError}_{audit}(K)
\]

낮을수록 좋다. 추가로 다음을 보고한다.

- 각 (K)에서 perturbation-specific error
- target accuracy 도달에 필요한 anchor 수
- uncertainty calibration
- pathway coverage
- seed·split variability
- acquisition batch 간 중복성과 다양성

### 7.5 Active Cartographer의 성공 기준

```md
Active Cartographer is supported only if:

1. Passive anchors improve the map over K=0 (Gate A).
2. The active policy improves AULC over random and the strongest one-shot
   baseline with a perturbation-level 95% CI excluding zero.
3. Improvement remains after Systema-style perturbation-specific evaluation.
4. Improvement is reproduced across multiple split seeds.
5. At least one additional biological context reproduces the direction before
   making a general context-adaptation claim.
```

---

## 8. Novelty 판단

다음 주장들은 이미 선행 연구와 크게 겹친다.

- active learning으로 다음 Perturb-seq target 선택
- 소수 seed로 새로운 context map 보정
- perturbation transport map 생성
- uncertainty가 높은 target 선택

ALIVE가 노릴 수 있는 더 선명한 novelty는 다음 조합이다.

> **A recoverability-aware active cartographer that chooses among PREDICT,
> MEASURE, and ABSTAIN to minimize the experimental cost of mapping a new
> cellular context while preserving calibrated population-level error.**

즉, 모든 불확실한 점을 측정하는 것이 아니라 다음을 구분한다.

- 이미 예측 가능한 영역
- 한 번 측정하면 주변 지도를 크게 개선하는 영역
- 현재 representation으로는 측정해도 일반화 이득이 낮은 영역

이 주장을 성립시키려면 Trust Gate가 단순 supervised error regressor를 넘어서고, acquisition policy가
best one-shot/active baseline보다 실험 효율을 높여야 한다.

---

## 9. 하드웨어 및 실행 가능성

현재 병목은 GPU가 아니라 데이터·평가 설계다.

- A100은 Replogle preprocessing, predictor training 및 여러 retrospective episode를 수행하기에
  충분하다.
- M5 Pro MacBook은 mini episode와 unit/integration test에 적합하다.
- Active acquisition 자체는 보통 target-level score 계산이므로 큰 GPU 비용을 요구하지 않는다.
- 가장 큰 비용은 여러 seed/split에서 predictor를 반복 재학습하는 부분이다. In-context adapter 또는
  warm-start checkpoint를 사용하면 줄일 수 있다.

실제 wet-lab round는 계산보다 시간이 더 큰 제약이다. Perturb-seq의 제한된 실험 round에서는 초기
오선택을 회복하기 어렵다는 지적이 있으므로 one-shot warm start를 기본값으로 두는 것이 안전하다.

---

## 10. 최종 권고

1. 현재 계획을 **Trust-Gate MVP**로 명확히 축소하고 실제 K562 decisive experiment까지 완성한다.
2. 별도 계획에서 **Passive few-shot Gate A**를 가장 먼저 수행한다.
3. Gate A가 성공할 때만 one-shot seed selection과 active acquisition을 비교한다.
4. Active policy는 random뿐 아니라 강한 graph/pathway one-shot baseline과 비교한다.
5. RPE1 단일 context 성공은 proof of concept로만 표현한다.
6. 추가 context 재현 전에는 universal 또는 causal cartographer를 주장하지 않는다.

결론적으로 Active Cartographer는 폐기할 아이디어가 아니다. 다만 현재 데이터로 타당한 목표는
**새로운 context를 제한된 perturbation budget으로 효율적으로 복원하는 retrospective active
mapping system**이다. 이 범위라면 구현도 가능하고 반증 가능한 연구 질문도 성립한다.

---

## 11. 주요 참고자료

- Huang et al. *Sequential Optimal Experimental Design of Perturbation Screens Guided by
  Multi-modal Priors.* RECOMB 2024. [DOI](https://doi.org/10.1007/978-1-0716-3989-4_2)
- Sextro et al. *MapPFN: Learning Causal Perturbation Maps in Context.*
  [arXiv](https://arxiv.org/abs/2601.21092)
- Dhaka et al. *HyperMap: An Efficient Framework for Transferring Perturbation Responses Across
  Diverse Biological Contexts.* [bioRxiv record](https://sciety.org/articles/activity/10.64898/2026.04.23.720505)
- Hao et al. *PerTurboAgent: A Self-Planning Agent for Boosting Sequential Perturb-seq Experiments.*
  [bioRxiv](https://doi.org/10.1101/2025.05.25.656020)
- Panagopoulos et al. *Efficient Data Selection for Training Genomic Perturbation Models.*
  [arXiv](https://arxiv.org/abs/2503.14571)
- Viñas Torné et al. *Systema: a framework for evaluating genetic perturbation response prediction
  beyond systematic variation.* [Nature Biotechnology](https://www.nature.com/articles/s41587-025-02777-8)
- Ahlmann-Eltze et al. *Deep-learning-based gene perturbation effect prediction does not yet
  outperform simple linear baselines.* [Nature Methods](https://www.nature.com/articles/s41592-025-02772-6.pdf)
- Bunne et al. *Learning single-cell perturbation responses using neural optimal transport.*
  [Nature Methods](https://www.nature.com/articles/s41592-023-01969-x)
- Roohani et al. *Virtual Cell Challenge: Toward a Turing test for the virtual cell.*
  [Cell](https://www.sciencedirect.com/science/article/abs/pii/S0092867425006750)

