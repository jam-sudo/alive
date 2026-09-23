# ALIVE Cartographer milestones

2026-09-23 현재 작업 트리·보존 artifact 기준. [목표 정렬 계약](2026-09-22-cartographer-realignment.md#goal-alignment)과
[governance](../../../CLAUDE.md#mission)를 따른다. 이 문서는 개발 순서와 완료 증거를 정하며,
scientific protocol·threshold·seal·실행 승인을 새로 정의하지 않는다.

## 목표와 완료의 의미

ALIVE는 **고정된 perturbation predictor의 예측이 어디서 얼마나 신뢰 가능한지 평가하고,
근거와 한계를 함께 전달하는 Cartographer**다. predictor 자체를 더 잘 학습하는 것이 현재 목표가 아니다.

- **50%:** owner가 지정한 실데이터 baseline 비교·오차·한계 보고. 개발 보고와 독립 검증을 구분한다.
- **100%:** 명시된 predictor·데이터·적용 범위 안에서 입력을 검증하고, 신뢰도 평가·사용/보류 판단·근거 보고를
  재현 가능하게 제공하는 연구용 Cartographer. 모든 세포·perturbation·predictor에 대한 일반화는 뜻하지 않는다.
- 50/100은 전달 단계의 명칭이지 코드량·test 개수로 계산한 측정값이 아니다. 중간 비율은 임의 부여하지 않는다.
- 음성 결과도 유효하다. `NO_DISTINCT_WIN`을 뒤집는 것이 완료 조건은 아니지만, 유용성이나 보장 범위를
  실제 근거보다 크게 주장해서는 안 된다. 개발 완료와 실증된 routing 우월성은 별도 축으로 보고한다.

## 단계별 milestone

| 단계 | 산출물·완료 조건 | 현재 상태 |
| --- | --- | --- |
| M0 — 목적·평가 계약 | frozen predictor, 측정할 error, claim unit, 허용 role, 비교군 및 non-claim을 명확히 구분 | 현재 목적·개발 규율 정렬 완료. TG 계약 존재; 새 protocol 활성화 아님 |
| M1 — 계산 핵심 | predictor/feature/response identity, trust score, 비교군, error metric, calibration, artifact/report 경로와 관련 회귀 검증 | 핵심 구현 및 로컬 검증 있음. 범용 입력 지원·모든 통계 edge case까지 완료한 상태는 아님 |
| M2 — 실데이터 증거 보고 **(50%)** | 동일 허용 unit의 전체 비교군, 실제 error·risk/coverage, exact N·제외, 불확실성/적정성의 범위, 한계와 재현 정보가 연결된 보고 | 실데이터 비교와 개발 supplement 확보. 현재 milestone에 적용되는 결손 재심사 및 통합 인계 판정 남음 |
| M3 — 재사용 가능한 query 경로 | 허용 입력 → frozen 평가 → score/bound/사용·보류 또는 지원 불가 사유 → 근거 연결을 한 경로에서 제공; fit·outcome 접근 없음 | 구성 요소 있음. 독립 사용자 경로와 identity/호환성 fail-closed 검증은 미완료 판정 |
| M4 — 신뢰도 지도와 한계 | 지원 영역별 실제 error·coverage·표본 수·불확실성/근거 부족 표시; query를 평가 근거에 연결하고 unsupported를 명시 | OOF 진단·전체 risk curve 등 부분 구현. 통합된 영역별 evidence map과 검증은 미완료 |
| M5 — 연구용 전달·검증 **(100%)** | 선언된 적용 범위에서 end-to-end 사용, 의미가 검증된 출력, versioned package/report, 재현·실패/변조 검사 및 적용 플랫폼 검증 | 미완료. M2–M4 증거와 범위별 인수 검사가 필요 |

M0/M1의 기존 구현은 유지·재사용한다. M2를 마치기 전에 M3–M5 전체를 선행조건으로 추가하지 않는다.
M3–M5의 schema·구체적 통계 규칙은 구현 전에 현재 protocol과 정합화하며, 이 표만으로 scientific run을 시작하지 않는다.

## 이미 구현되거나 확보된 것

아래는 파일 존재만이 아니라 코드 경로와 기존 검증 기록을 대조한 inventory다.
전체 회귀는 2026-09-23 보존 기록상 4,600 passed / 51 skipped / 4 warnings이며,
이번 계획 수립에서 재실행한 결과가 아니다. Mac 결과는 Linux isolation proof를 대신하지 않는다.

| 기능 | 현재 근거 | 남아 있는 경계 |
| --- | --- | --- |
| Frozen predictor 복원 | [BasePredictor](../../../src/alive/base/predictor.py), [검증 기록](../audits/2026-09-23-cartographer-source-feasibility.md): predictor/response reader·checksum 확인, fit 표적 740개 일치 | 새 입력의 gene-axis·feature 호환성은 별도. 새 학습 불필요는 모든 입력 지원을 뜻하지 않음 |
| Feature·role 관리 | [FeatureBank](../../../src/alive/data/features.py), [manifest](../../../src/alive/data/manifest.py); 보존 bank 1,989개, 기존 eligible 1,645개 포함 | 나머지 344개는 기존 제외 목록. 새 평가 표본으로 간주하지 않음 |
| Trust score·비교군 | [TrustGate](../../../src/alive/gate/recoverability.py), [baselines](../../../src/alive/baselines/uq.py): gate, ensemble disagreement, nearest feature, residual-only, GBM-error, ridge-error | score는 per-query 정답 확률이 아님. 우월성은 구현에서 따라오지 않음 |
| 실제 error·선택 성능 | [distance](../../../src/alive/metrics/distance.py), [selective](../../../src/alive/metrics/selective.py), [bootstrap](../../../src/alive/eval/bootstrap.py) | energy distance의 scale, tie rule, paired unit 및 CI 적용 범위를 명시해야 함 |
| Calibration·보류 기준 | [error_bound](../../../src/alive/conformal/error_bound.py): scalar bound, gate-score threshold, coverage 진단 | marginal coverage ≠ selected/conditional guarantee. 작은 N의 rank clipping은 일반 적용 전 계약·의미 검토 필요 |
| 실행·보고·진단 | [real_runner](../../../src/alive/experiment/real_runner.py), [report](../../../src/alive/eval/report.py), [diagnostics](../../../src/alive/eval/diagnostics.py) | 기존 report는 terminal artifact 기반으로 verdict를 재계산하지 않음. 새 user-facing API/지도 완료와는 다름 |
| Serialization 보강 | [MethodLock](../../../src/alive/experiment/develop.py), [precision tests](../../../tests/alive/experiment/test_methodlock_precision.py), [runner tests](../../../tests/alive/experiment/test_real_runner.py) | v2 precision·tamper 검사와 향후 CI retention 보강. 과거 유실 수치 복구 아님; 미커밋 변경 포함 |
| 실제 비교 결과 | TG `d18c601b6855b3b1`, 평가 N=247, 개발 supplement N=411; [evidence audit](../audits/2026-09-22-cartographer-evidence-gaps.md) | `NO_DISTINCT_WIN` 유지. 두 N을 합치거나 개발 결과를 독립 평가로 바꾸지 않음 |

세부 테스트는 `tests/alive/{base,data,gate,baselines,metrics,conformal,eval,experiment}/`에 있다.
실행 증거는 `artifacts/cartographer-regression-20260922/RETENTION02.md` 및 log/JUnit에 보존되어 있다.
로컬 handoff의 `2026-09-23-cartographer-dev-supplement.md`와 JSON은 개발 error 분포,
6종 AURC·25/50/70/100% risk 및 provenance를 포함한다. 원본 데이터·checkpoint는 git에 넣지 않는다.

## M2: 지금 끝낼 작업과 판정 방법

1. **기존 결과를 하나의 인계 문서로 연결한다.** frozen predictor identity, 보존 평가와 개발 supplement의
   scope·N을 분리하고 모든 trust comparator, 실제 error 분포, risk/coverage, 실패·제외·한계를 찾을 수 있게 한다.
   기존 수치를 다시 계산하거나 terminal run을 재실행하지 않는다.
2. **각 결손의 적용 범위를 판정한다.** 결손마다 `필수 산출물 / 근거 원문 / 현재 증거 / 현 milestone blocker인지 /
   적법한 최소 보완`을 기록한다. 옛 exact invocation·seed-wise 출력·sealed raw summary 부재를 숨기지 않되,
   그것이 모든 개발 보고를 금지하거나 새 independent holdout을 의무화한다고 자동 추론하지 않는다.
3. **적정성과 불확실성을 정직하게 처분한다.** inference가 허용되는 결과에만 해당 CI를 사용한다.
   exploratory 결과는 selection·legacy precision·biological N 부재의 영향을 명시하고 미입증 claim을 하지 않는다.
   모든 결손을 단순히 '한계'라 부르며 필수 검증을 면제하지 않는다.
4. **완료 판정한다.** 실데이터·전체 비교군·오차·범위/한계·재현 가능한 인계가 실제로 충족되었는지 확인한다.
   필요조건이 남으면 해당 조건만 보완한다. 새 데이터/실험은 기존 허용 증거로 해결되지 않는 필요성이 입증된 뒤 선택한다.

M2의 현재 상태는 **근거 확보 / 완료 판정 대기**다. 이전의 [미완료 audit](../audits/2026-09-23-cartographer-milestone-disposition.md)는
결손 목록으로 보존하며 그 요구의 milestone 적용 범위를 재심사한다. 이 로드맵 작성 자체로 50%를 선언하지 않는다.

## M3–M5의 인수 조건

- M3: 지원 predictor/input identity를 명시하고, 잘못된 gene 순서·중복/누락 feature·변조·지원 외 입력을
  검출하는 검사를 둔다. 같은 입력/버전의 결과는 재현되어야 하며 query 경로가 fit/calibration/새 outcome 읽기를
  호출하지 않아야 한다. bound 적용 조건이 충족되지 않으면 보장을 붙이지 않고 이유를 반환한다.
- M4: '지도'는 화려한 embedding plot이 아니라 query가 어떤 평가 근거 영역에 속하는지와 그 영역의 실제
  error·표본 수·한계를 보여주는 것이다. 전체 평균을 개별 query 보장으로 바꾸지 않는다. 영역 정의·비교를
  outcome 보고 사후 최적화했다면 exploratory로 표시하고, 독립 검증 없이 검증된 영역이라 부르지 않는다.
- M5: 명시된 사용 시나리오를 다른 사용자가 재현하고, score·bound·보류의 의미와 지원 범위를 오해 없이
  확인할 수 있어야 한다. 적용 범위의 실증 근거와 선언하는 통계 보장에 맞는 검증이 있어야 하며,
  단순히 UI/API가 동작하거나 CI가 green인 것으로 대체하지 않는다. 새 과학적 검증이 필요하면 별도 승인 경계를 따른다.

GUI, 여러 predictor adapter, 새 cell line, 시간 전이, 약물 데이터, active acquisition, 새 deep predictor는
이 milestone의 자동 필수조건이 아니다. 단일 지원 경로부터 완성하며 확장은 입증된 필요 또는 owner의 새 목표에 따른다.

## 추가 검토 2회

**검토 1 — 목표 정렬:** 새 데이터와 모델 개발을 진척의 대리변수로 쓰지 않았다. M2에 제품화·환경 전이를
추가하지 않았고, 기존 실제 비교·구현을 명시적으로 인정했다. 100%를 범용 virtual-cell 완성으로 확대하지 않았다.

**검토 2 — 과학·완료 과장:** 구현/실데이터 증거/독립 검증/사용 가능한 전달을 구분했다. negative verdict,
미검증 biological N, calibration 조건, historical gaps를 유지했다. 요구사항 대비 근거의 완료 판정 없이
50% 완료를 선언하지 않았다. 완료 판정을 위해 별도의 형식적 owner 결재 단계를 추가하지 않는다.
Protocol 상태·seal·config는 바뀌지 않았고, 두 검토는 scientific execution approval의 대체물이 아니다.
