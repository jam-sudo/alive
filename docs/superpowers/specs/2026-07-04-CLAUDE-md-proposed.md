# ALIVE — Virtual Cell Project Governance

> **⚠ SUPERSEDED (2026-07-08) — historical proposal only.** 이 제안본은 적용된 root
> `CLAUDE.md`가 아니며 현재 protocol 상태·release gate·agent instruction의 source가 아니다.
> 현재 거버넌스는 repository root `CLAUDE.md`, 실행 준비도는
> `docs/superpowers/COMPOSE-SEAL-READINESS.md`를 따른다. 아래 본문은 당시 제안 기록으로 보존한다.

> **역할:** project-wide scientific governance + agent operating contract
> **개정일:** 2026-07-04
> **활성 protocol:** `COMPOSE-K562-v1` (ACTIVE, 2026-06-30 activation; `TG-K562-v1` COMPLETE)
> **다음 milestone:** COMPOSE sealed double-unseen 확정 실행(A100, 1회) → `CT-RPE1-v1` (deferred)

이 문서는 매 세션 **전체가 context에 로드된다.** 따라서 여기에는 protocol-independent safety invariant와
agent operating contract만 둔다. Milestone별 세부(exact split·threshold·seed·metric·grid·roster)는
versioned spec/plan/config가 authoritative이며, 여기서는 가리키기만 한다(§1). 새 milestone 세부를 이
문서에 추가하지 않는다.

---

## 1. Sources of truth & 충돌 처리

문서 계층 — **도메인별** 우선순위:

1. Safety · seal · leakage · governance invariant → **이 문서 (`CLAUDE.md`)**
2. Scientific claim 정의 → 해당 milestone versioned **design spec** (spec §0)
3. Execution contract → 해당 milestone **implementation plan**
4. Exact split · threshold · seed · metric → committed **protocol/config**
5. Runtime behavior → `src/alive/`
6. Vision → `virtual-cell-model-blueprint.md` · Evidence → `virtual-cell-research-report.md` ·
   Long-range → `virtual-cell-project-plan.md`

Safety invariant는 이 문서가 최상위, claim 정의는 milestone spec이 최상위다. 두 도메인이 직접 충돌하면
(예: safety invariant가 어떤 claim 구성을 금지) **safety invariant가 우선하여 run을 중단**시킨다.

**충돌은 조용히 해결하거나 편리한 쪽을 고르지 않는다.** 문서가 충돌하면:

1. 충돌을 보고한다.
2. active protocol과 affected invariant를 식별한다.
3. scientific run을 시작·계속하지 **않는다.**
4. owner가 명시적으로 reconcile하게 한다.
5. 변경 후 새 run identity와 artifact lineage를 만든다.

현재 active protocol의 spec/plan/config는 §5 registry의 `COMPOSE-K562-v1` 항목이 가리킨다.

---

## 2. Mission (요약)

ALIVE는 단계적으로 causal virtual-cell world model을 구축한다. 장기 target:

$$p(X_{post}\mid P_{control}, A, C)$$

$P_{control}$ = control-cell population(paired individual cell 아님), $A$ = intervention/CRISPRi
target, $C$ = context, $X_{post}$ = post-intervention cell-population distribution.

현재는 특정 milestone MVP만 활성이며(§5), 그 이상을 주장하지 않는다. 다음 용어는 근거 없이 쓰지 않는다:
mechanistic · causal · temporally resolved · clinically predictive · distribution-valued
prediction-set · Active Cartographer. 현재 additive/bilinear base의 결과를 deep virtual-cell 성과로
표현하지 않는다.

---

## 3. Universal scientific invariants — **모든 protocol에 적용**

1. **Protocol first.** train/tune/eval 전에 active protocol, manifest, primary metric, comparator
   family, failure condition을 version-control한다.
2. **Baseline first.** learned model 성과를 보기 전에 registered baseline과 evaluation harness를
   구현한다.
3. **Seal evaluation outcomes.** active protocol의 evaluation outcome은 model/method selection이
   freeze된 뒤 authorized evaluation code에서만 접근한다.
4. **Fit on training roles only.** normalization · feature selection · embedding · calibration ·
   hyperparameter · threshold는 protocol이 허용한 role만 쓴다.
5. **No outcome-selected test set.** evaluation universe는 metadata · external-feature availability ·
   사전등록 QC로 정한다. response strength나 base error로 고르지 않는다.
6. **Split at the claim unit.** perturbation-level claim은 perturbation ID로 split한다. cell-barcode
   split으로 unseen-perturbation claim을 만들지 않는다.
7. **Match claim to split.** K562-internal split은 new-context transfer를, shared-target split은
   unseen-target generalization을 증명하지 않는다.
8. **Risk is measured outcome error.** routing utility를 conformal bound · confidence score · 자기
   자신의 threshold로 평가하지 않는다.
9. **Coverage is table stakes.** calibration validity 자체를 routing novelty로 광고하지 않는다.
10. **No single-metric win.** primary metric · registered secondary metric · effect size ·
    perturbation-level CI · failed run을 모두 보고한다.
11. **Interrogate systematic variation.** batch · cell cycle · target-panel bias · common treatment
    shift · mean collapse를 점검한다.
12. **Do not overclaim heterogeneity.** responder/non-responder · multimodality는
    outcome-independent 정의와 noise audit 없이 주장하지 않는다.
13. **Uncertainty needs a method.** raw variance를 aleatoric/epistemic uncertainty로 부르지 않는다.
    estimator · calibration role · coverage event를 명시한다.
14. **Negative results are results.** futility · calibration failure · invalid evaluation ·
    no-distinct-win을 삭제·대체하거나 threshold를 사후 변경하지 않는다.

---

## 4. Seal & immutability contracts — **safety core**

### 4.1 Seal 원칙 (protocol-independent)

- evaluation outcome은 selection freeze 후 authorized code에서만, **protocol당 정확히 한 번** 연다.
- fit/develop/calibrate 단계의 sealed access count는 **0**이어야 한다.
- futility-stopped run은 sealed access count 0으로 영구 종료한다. **futility ≠ negative verdict.**
- **서로 다른 protocol의 seal은 대체 불가.** 하나의 run ID·audit file·result가 두 protocol seal을 동시에
  대표할 수 없다. cross-protocol 비교는 각 protocol의 immutable artifact를 입력으로 받는 별도 analysis다.

### 4.2 Run identity & write-once (provenance)

모든 run은 기록한다: protocol name/version · resolved config · dataset/data-card hash · manifest/
exclusion hash · feature-bank/sequence-map hash · seed · Git SHA · dependency-lock hash ·
device/precision · stage artifact checksum · seal-access audit · report checksum.

Run directory와 ledger는 **write-once state machine**이다:

- existing run을 조용히 덮어쓰지 않는다.
- resume은 upstream hash가 byte-identical할 때만 허용한다.
- ledger entry를 새 checksum으로 교체하지 않는다.
- terminal status 또는 seal access 후 upstream stage를 재실행하지 않는다.
- input lineage가 달라지면 새 run identity를 쓴다.

---

## 5. Protocol registry

정확한 split·verdict·claim은 각 protocol의 spec/plan/config가 authoritative다. 이 표는 claim을 정의하지
않는다.

| protocol | status | 한 줄 목적 | 문서 · seal |
|---|---|---|---|
| `TG-K562-v1` | COMPLETE | K562-internal held-out에서 Trust-Gate가 사전등록 UQ comparator보다 prediction error를 잘 순위화하는가 (sealed verdict: **NO_DISTINCT_WIN**) | spec `docs/superpowers/specs/2026-06-20-cartographer-design.md`; plan `.../plans/2026-06-20-cartographer-mvp.md`; config `configs/cartographer_trust_gate_k562_v1.yaml`; K562-internal seal (opened once) |
| `COMPOSE-K562-v1` | **ACTIVE** | Norman K562 CRISPRa combo에서 단일-gene signature로 고정한 factor로 비가산 성분을 identifiable bilinear operator로 예측 | spec `docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md`; config `configs/compose_k562_v1_phase2.yaml`; 독립 COMPOSE seal |
| `CT-RPE1-v1` | DEFERRED | K562→RPE1 shared-target **context transfer** 평가 (clean cell-type split 아님) | 별도 spec/config/seal 필요 (미작성) |

**`COMPOSE-K562-v1` (ACTIVE, 2026-06-30 activation).** spec §10.1의 activation blocker가
version-controlled evidence/test(`docs/activation-evidence/compose/`, `docs/data-cards/`)로 충족되어
real Phase-2 fit과 sealed outcome 접근이 인가됐다. 단:

- 실제 sealed confirmatory run은 A100에서 유효한 `ActivationRecord`(requirement별 non-empty evidence
  hash) + clean git tree로만 실행된다.
- COMPOSE seal은 `TG-K562`와 **독립적으로 정확히 한 번** 열린다. **아직 열리지 않았다.**
- activation은 기존 결과에 **소급 적용하지 않는다.**

**`CT-RPE1-v1` (DEFERRED).** cell line · experiment · batch · endpoint day가 함께 변하는
cross-dataset context transfer다. 다음이 모두 있기 전엔 활성화하지 않는다: owner approval · 별도
spec/config · shared-target manifest · RPE1-specific leakage test · K562 seal과 독립된 RPE1 outcome
store/audit · adequate sample-size/detectable-effect 분석. RPE1 perturbed outcome 접근은 이 protocol
활성화를 요구한다. 활성화 시 RPE1 seal 규칙 적용: control은 inference context 사용 가능; perturbed
outcome은 selection freeze 후 evaluation code만; response strength로 target 선택 금지; audit는
TG-K562와 별도 저장.

R2/R3 · causal masking · Norman/Tahoe OOD · combo · drug · time series · distribution-valued set ·
Active Cartography는 각각 별도 이름·spec·seal·success criteria가 필요한 후속 protocol이다.

---

## 6. Data · model · baseline · evaluation governance

세부 grid·roster·threshold는 active spec/config가 정한다. 아래는 protocol-independent 규칙이다.

**Data** (`src/alive/data/`). source: versioned Replogle processed Perturb-seq AnnData(`.h5ad`). raw
counts·provenance 보존; sparse/on-disk/chunked access, bounded population/minibatch만 densify.
manifest에 asset·day·endpoint·target universe 기록. `K562_gwps`를 `K562_essential` 대신 조용히 쓰지
않는다. cell-count/UMI threshold를 universal fact로 hardcode하지 않고 실제 분포를 profile해 threshold와
sensitivity를 사전등록한다. raw/processed data·checkpoint·credential·identifiable donor data를 commit
하지 않는다. large transfer 전 size·destination·license를 확인한다. external feature eligibility는
split 전에 확정하고, missing/ambiguous sequence를 split 후 조용히 건너뛰지 않는다.

**Model / feature.** requested encoder(예: ESM) 실패를 mock으로 조용히 대체하지 않는다(mock은
synthetic/CI 전용). feature-bank revision·dimension·pooling·config를 대조하고 long-sequence policy와
sequence database release를 기록한다. deep encoder·low-rank operator·OT-CFM·NB decoder 등 새
architecture는 별도 spec과 baseline/ablation이 필요하다. population sample 출력이 heterogeneity 학습을
뜻하지 않는다 — pseudobulk·mean·self-distance floor·mean-collapse diagnostic를 유지한다.

**Baseline.** 모든 protocol은 strongest eligible baseline과 비교하고, roster는 evaluation outcome을
보기 전에 고정한다. biological gene/pathway/network encoder는 ID-only baseline과 ablation한다.

**Evaluation.** versioned evaluation protocol을 comparison 전에 freeze한다. primary metric의 방향과
scientific event를 명시하고 toy known-answer test를 둔다. strongest comparator를 사후 선택해 ordinary
pairwise CI를 적용하지 않고, comparator-family selection을 반영한 **simultaneous inference**를 쓴다.
secondary biological/distributional metric의 material-regression margin을 사전등록한다. per-target ·
null/weak behavior · seed variability · self-prediction/noise ceiling · failed run을 보고한다.
**futility status와 scientific verdict를 혼합하지 않는다.** independent prospective hit-rate validation은
별도 milestone이다.

---

## 7. Repository & compute conventions

```text
src/alive/
  data/ base/ gate/ baselines/ conformal/ metrics/ eval/ experiment/   # TG-K562 pipeline
  compose/                                                             # COMPOSE outcome store · terminal state machine · provenance2 (ACTIVE)
  cli.py config.py io.py provenance.py types.py                        # top-level modules
configs/   tests/   docs/   artifacts/(gitignored)
```

- Python version은 `pyproject.toml`을 따른다. public API에 type hint + NumPy-style docstring. Ruff
  line length 100 + committed lockfile.
- hardcoded path · split ID · threshold · feature list · seed · hyperparameter를 production source에
  넣지 않는다. production logic은 `src/`, notebook은 library function만 호출한다.
- 명령을 추측하지 않는다 — `pyproject.toml` · CLI help · README를 확인한다.

**Compute.** MacBook(M5 Pro, 24GB, CUDA 없음): setup · unit test · bounded inspection · CPU/MPS
smoke · mini end-to-end · docs · reproducibility. A100: original-data acquisition · integrity ·
preprocessing · real ESM feature · full run. mini와 full은 **동일 production code**, config만
scale/device 변경. mini의 leakage · metric · provenance · resume 검증 후 full 시작. device fallback을
숨기지 않고, ephemeral disk를 artifact 유일본으로 쓰지 않으며, cloud run은 instance/GPU · image/lock ·
input hash · Git SHA · config · wall time · cost를 기록한다.

---

## 8. Agent operating contract

**작업 순서.**

- inspect before editing. scientifically consequential change 전 affected invariant·protocol을 먼저
  식별한다. unrelated user change를 보존하고, established protocol을 조용히 rewrite하지 않는다.
- 현재 hypothesis를 falsify할 수 있는 가장 작은 실험을 선호한다. 좋은 결과일수록 leakage · batch
  confounding · mean collapse · metric gaming · seed sensitivity를 먼저 검사한다.
- evidence level과 uncertainty를 명시한다. preprint · vendor · model-generated claim을 ground truth로
  취급하지 않는다.
- 규칙이 타당한 작업을 막으면 우회하지 말고 충돌을 보고한다(§1).

**완료 전 검증 (관련 변경마다).** targeted unit test → applicable integration test → Ruff lint/format →
(data/evaluation 변경 시) leakage test → (metric 변경 시) known-answer·constant·shuffled·random
sanity → (artifact/provenance 변경 시) tamper·resume test. 실행한 명령·결과·skip·미완 검사를 보고한다.
**scientific run 전에는 active spec/plan/config와 runtime behavior의 contract audit를 수행한다. 문서와
코드가 충돌하면 test가 통과해도 run을 시작하지 않는다.**

---

## 9. Governance summary

```text
COMPLETE : TG-K562-v1        — K562 four-way split, sealed eval, verdict NO_DISTINCT_WIN
ACTIVE   : COMPOSE-K562-v1   — Norman K562 CRISPRa pair-level split, independent COMPOSE seal
                                (activated 2026-06-30; opens once; A100 sealed run pending)
DEFERRED : CT-RPE1-v1        — K562 → RPE1 shared-target context transfer, independent RPE1 seal
RULE     : protocol seal · claim · manifest · run ID · report는 상호 교환 불가.
```

<!-- maintainer note: 이 문서는 매 세션 전체 로드된다. milestone 세부는 여기 추가하지 말고 spec/plan/config에 둔다. 상태 변경(활성 protocol, seal open 등) 시 §5 표와 §9 요약만 갱신한다. -->
