# Paper review — Advancing AI for multi-omics and clinical data integration in basic and translational cancer research

> **유형:** literature review note (외부 논문 요약)
> **작성일:** 2026-06-28
> **스코프:** abstract + 그림 캡션 + 색인 기반 재구성. 본문(full text)은 Nature 로그인 게이트라
> 섹션 세부는 부분적임. 직접 인용은 abstract만 verbatim.

---

## 1. 서지 정보

| 항목 | 값 |
|---|---|
| 제목 | Advancing AI for multi-omics and clinical data integration in basic and translational cancer research |
| 저자 | Fei Liu, Stephan Beck, Lei Yang, Huiyan Luo, Kang Zhang |
| 저널 | *Nature Reviews Cancer*, vol. 26, pp. 497–512 |
| 출판일 | 2026-04-21 |
| 유형 | Review Article |
| DOI | [10.1038/s41568-026-00922-2](https://www.nature.com/articles/s41568-026-00922-2) |

소속(부분): Stephan Beck = UCL 후성유전체학 계열; Kang Zhang = 정밀의료 / AI-진단 계열.

---

## 2. Abstract (verbatim)

> "The extensive heterogeneity of cancer across biological scales necessitates a holistic
> approach beyond single-analyte methods. Integrating multi-omics data — from genomics to
> proteomics — with multimodal information, such as clinical records and medical imaging,
> offers a comprehensive, systems-level view of tumorigenesis. Artificial intelligence (AI)
> has emerged as the essential technology to decipher these complex, high-dimensional
> datasets, powering substantial advances in early diagnosis, precise patient stratification,
> prediction of therapeutic response and the elucidation of mechanisms of drug resistance.
> To translate these powerful predictive models into practice, explainable AI is critical for
> building clinical trust and generating novel, testable biological hypotheses. While
> challenges in data accessibility and model generalizability persist, the field is advancing
> toward patient-specific digital twins, promising to simulate individual disease trajectories
> and optimize treatments, thereby heralding a new era of precision oncology."

---

## 3. 핵심 논지

암은 생물학적 스케일 전반의 이질성(heterogeneity)을 가지므로 단일 분석물(single-analyte)
접근으로는 부족하고, **multi-omics(genomics→proteomics) + multimodal(임상기록·의료영상)** 통합으로
systems-level 관점을 확보해야 한다. 그 고차원 데이터를 해독하는 **필수 기술이 AI**이며, 이를 통해:

1. 조기 진단(early diagnosis)
2. 환자 stratification
3. 치료 반응 예측(therapeutic response)
4. 약물 내성 기전 규명(drug resistance)

에서 진전이 있었다. 임상 적용에는 **explainable AI(XAI)** 가 신뢰 확보 + 검증 가능한 생물학적
가설 생성에 핵심이고, 궁극적 지향점은 **patient-specific digital twins**(개인별 질병 궤적
시뮬레이션 → 치료 최적화)다.

---

## 4. 리뷰 구조 (그림 기준 스캐폴드)

| Fig | 제목 | 내용 |
|---|---|---|
| 1 | The multi-omics data foundation for precision oncology | 데이터 토대 |
| 2 | AI methodologies for multi-omics data integration | 통합 방법론 |
| 3 | Conceptual framework of developing and utilizing **digital twins** in oncology | digital-twin 프레임워크 |
| 4 | The **AI-driven oncological multi-omics loop** | 측정→모델→가설→재측정 폐루프 |

---

## 5. 거명된 방법·도구·데이터셋

**아키텍처 / 방법**
- deep learning (CNN, transformer)
- graph convolutional networks — **MOGONET**
- GAN, diffusion models
- multiple-instance learning
- federated learning
- foundation models, transfer learning
- explainable AI (XAI)

**구체 시스템**
- **Molecular Twin** — 췌장암 예후
- **AlphaMissense** — 변이 효과 예측
- **Sybil** — 폐암 위험 예측
- **Cell Decoder** — 세포 정체성 분류

**데이터 리소스**
- ICGC / TCGA Pan-Cancer
- **MSK-CHORD** — real-world 종양학 코호트

---

## 6. 도전 과제 & 미래 방향

1. **Data accessibility** — 학습용 통합 데이터 확보의 구조적 한계.
2. **Generalizability** — cross-institutional / 다인구 외부검증에서 성능 저하; robust validation 미해결.
3. **Explainable AI** — 임상 신뢰 + testable hypothesis 생성의 전제 조건.
4. **Digital twins** — 개인별 disease trajectory 시뮬레이션으로 치료 최적화하는 최종 프런티어.

---

## 7. ALIVE 관점에서의 함의

이 리뷰의 두 축 — **Fig. 4의 measurement→model→hypothesis→re-measurement 폐루프** 와
**digital twins** — 는 ALIVE의 north-star(예측 불가 영역에서 *측정을 요청*할 수 있는 causal
virtual-cell world model = active cartography)와 개념적으로 같은 방향이다.

차이/주의:
- 이 논문 스코프 = **임상/translational oncology + 환자 단위 multimodal**.
- ALIVE 현재 MVP 스코프 = **단일 cell-line(K562) perturbation-response surrogate + conformal
  trust-gate**.
- 추상화 수준이 다르므로 직접 차용보다 "closed-loop + generalizability/XAI를 1급 시민으로 두는
  framing"이 참고점. **과대 매핑 금지** — 둘은 다른 도메인.

---

## 8. 출처

- [Nature Reviews Cancer — article page](https://www.nature.com/articles/s41568-026-00922-2)
- [New horizons at the interface of AI and translational cancer research (Cancer Cell)](https://www.sciencedirect.com/science/article/abs/pii/S1535610825001199)
- [AI-driven multi-omics integration in precision oncology (Clin Exp Med / PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC12634751/)
