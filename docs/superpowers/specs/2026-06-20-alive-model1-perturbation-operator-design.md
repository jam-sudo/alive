# ALIVE Model #1 — Perturbation-as-Operator (A-centered hybrid) · FINAL 설계 스펙

> **⚠ SUPERSEDED / long-range-parked (2026-07-04).** 이 "확정 설계"는 `CLAUDE.md` §4 protocol registry에
> 등록되지 않았고 어떤 active spec도 참조하지 않는다. 핵심 capability(Cell-B mean win by architecture)가
> prior-art 대비 non-novel로 판명되어 `COMPOSE-K562-v1`(비가산 epistasis operator)로 pivot했다.
> unseen-target transfer 축은 `CT-RPE1-v1`(DEFERRED)로 이관했다. 이 문서는 long-range 참고로만 보존한다.
> (개정일 필드 없음 — 2026-06-20 작성 기준.)

> 상태: 설계 확정안 (project owner 검토용). MVP = 단일유전자 예측 surrogate. **causal/mechanistic 주장 금지**, 식별성은 "제약된 가설공간"으로만 표현. 모든 win 주장은 perturbation-level bootstrap 95% CI 하한 > 0 + 사전등록 보조지표 무회귀로만 인정.
>
> 이 문서는 4개 컴포넌트 설계(operator-formulation / gene-feature-encoder / distributional-decoder / cellB-win-eval-roadmap)를 통합하고, critique panel의 모든 fatal_flaw·serious_concern·required_fix를 (a) 설계에 직접 반영하거나 (b) 명시적 accepted risk + 완화책으로 처리한 결과다. 가장 무거운 비판 — **"state-dependent 항은 pseudobulk 평균에 수학적으로 0을 기여하므로, PDS/DES로 결정되는 Cell B win과 분리된다"** — 을 §2.4와 §4에 정면으로 박았다.

---

## 1. 한 줄 정의 + 무엇이 새로운가

### 1.1 한 줄 정의
각 perturbation $g$ 를 ID 룩업이 아니라 **유전자 기능 피처 $\phi_g$ 로부터 하이퍼네트워크가 예측하는, 잠재 세포상태 $z$ 위에 작용하는 저랭크 affine 연산자 $M_g = I + U_g V_g^\top$ (bias $b_g$)** 로 표현하고, 그 연산자가 변형한 control 잠재집단을 출발점으로 하는 **조건부 flow matching(CFM)** 으로 perturbed **집단 분포**를 생성하는 모델.

### 1.2 정직한 novelty 회계 (genuine vs reduces-to-existing)

critique panel 3인의 공통 판정은 "fixable이지만, 손대지 않으면 기존 조합으로 환원된다"이다. 그 환원 경로를 **부정하지 않고 명시**한다.

| 구성요소 | 기존 대응물 | 진짜 새로운가? |
|---|---|---|
| 잠재 encoder + OT-CFM velocity + NB decoder | **CFM-GP / CellOT 계열** | ✗ 새롭지 않음. 이건 검증된 분포 backbone을 그대로 채택 |
| $b_g = f_\phi(\phi_g)$ (feature→shift) | **CPA additive shift / feature-linear baseline** (CLAUDE.md Registered #3/#4), GEARS류 | ✗ 형태상 동일. MLP 대 선형 W의 차이뿐 |
| 분포 출력 (mean-MSE 대신 CFM) | CFM-GP/Departures | △ CPA/GEARS(mean-MSE) 대비는 진짜 다름. 단 CFM-GP/Departures 자체가 **novel perturbation(Cell B)에서 미검증** |
| **state-dependent 곱셈항 $U_g V_g^\top z$** | CPA에 없음 (CPA는 $F0$=가산만) | ◎ **유일하게 새로운 핵심 항.** 단 §2.4 참조 — 이 항은 평균이 아니라 **분산/이질성**에만 쓰인다 |
| composition algebra (dose=$\exp(\delta L)$, 조합=$M_1M_2$) | — | 형식적으로 새롭지만 **MVP에서 학습 신호 0 → 검증 불가** |

**솔직한 결론 (panel fix 반영):**
1. MVP에서 검증 가능한 단 하나의 novelty는 **state-dependent 저랭크 항**이다.
2. composition algebra는 단일유전자 Replogle에 신호가 0이므로 **spine 선택의 정당화 근거에서 제외**한다(아래 §6, §8 R-12). F1을 고른 이유는 "조합에 닫혀서"가 **아니라**, 단일유전자에서 "(a) CPA를 strict superset으로 nest해 공정 ablation 가능 + (b) 상태 의존 이질성을 분산 차원에 구조적으로 도입"하기 때문으로 재정당화한다.
3. 따라서 **이 모델의 정직한 헤드라인은 "Cell B를 이긴다"가 아니라 "Cell C(context transfer)를 1차 목표로 하고, Cell B는 falsification 축"** 이다(§1.3, §6).

### 1.3 무엇을 "이긴다"고 주장하는가 — scope을 좁힌다
- **1차 합격 목표 = Cell C (K562→RPE1 context transfer).** 난이도 A<C<B<D, plan 정합.
- **Cell B = 진단/falsification 축.** north-star가 "Cell B PRIMARY"를 원하지만, §2.4의 수학 때문에 현재 형태로 Cell B의 PDS/DES를 이길 메커니즘이 약하다. 이 긴장을 숨기지 않고 §8 미해결 #1로 owner 결정에 올린다. **기본 입장: Cell C 1차, Cell B는 "feature_operator > feature_linear (CI>0)" 단일 가설의 falsification.**
- Cell C win은 **"context transfer"로만** 주장. cell line·experiment·batch·day·endpoint 동시 변동이라 "cell-type generalization"으로 과대주장 금지.

---

## 2. 모델 구조

### 2.0 전체 파이프라인
```
X_ctrl (HVG counts)
  │  E_ψ  (cell encoder; scVI-style, batch-aware ← RPE1 CONTROL only; §2.1)
  ▼
z_ctrl ∈ R^d  (d=32~64)          ← 출발 분포 P0 = { z_ctrl^(i) }
  │  M_g = I + U_g V_g^T,  bias b_g    (operator spine; φ_g→하이퍼네트워크 §2.3)
  ▼
z0^(i) = M_g · z_ctrl^(i) + b_g       (bridge 출발점)
  │  [OT-CFM ODE]  dz/dt = v_θ(z, t | h_g, c),  t:0→1   (§2.4 결합)
  ▼
z_post  (perturbed 잠재 집단)     ← 도착 분포 P1
  │  D_φ  (NB/ZINB head)
  ▼
X_post  →  (a) 집단 count 분포 [E-dist/MMD/Sinkhorn]
           (b) DETERMINISTIC 평균경로 [PDS/DES/weighted-ΔR²]  ← §4.2
```

### 2.1 Latent state & encoder $E_\psi$
- control·perturbed **공유** encoder. 잠재차원 $d=32\sim64$ (작게: ODE/OT 차원저주·고차원 Wasserstein 붕괴 회피).
- **[FIX — feasibility panel #2 해결]** encoder를 K562-only로 적합하면 Cell C에서 RPE1 control이 OOD가 되어 bridge 출발점·연산자 좌표가 모두 어긋난다. 이는 1차 목표(Cell C)를 직접 위협하므로 **Phase 3 이전에 결정**: encoder를 **batch-aware**로 만들되 배치 공변량은 **RPE1 *control* 만** 사용(scVI batch covariate; CLAUDE invariant #3 — RPE1 perturbed outcome 미접촉 — 준수). 이로써 RPE1 control 잠재가 in-distribution이 되고 $U_g,V_g$ 의 read/write 좌표가 RPE1 control geometry와 정렬된다.
- **검증 게이트:** encoder 적합 후 RPE1-control 재구성 오차/잠재밀도를 측정해 OOD가 아님을 확인한 뒤에만 Cell C transfer를 win으로 주장(§5, §7).

### 2.2 연산자 $M_g$ — 저랭크 affine (채택 spine = F1)
$$ z' = M_g\, z + b_g, \qquad M_g = I + U_g V_g^\top,\quad U_g,V_g\in\mathbb{R}^{d\times r},\ r\ll d. $$
- $(U_g, V_g, b_g) = f_\phi(\phi_g)$ (§2.3). 적용은 $M_g z = z + U_g(V_g^\top z)$ — $d\times d$ 행렬·det·inverse 절대 미생성, $\mathcal{O}(dr)$.
- **CPA를 strict superset으로 nest:** $U_g V_g^\top = 0$ 이면 정확히 CPA(가산 shift $b_g$). → §8 kill-gate ablation이 공정하게 성립.
- rank $r\in\{1,2,4,8\}$ 핵심 하이퍼파라미터. $r=1$ ($M_g=I+u_g v_g^\top$)이 가장 해석가능·GRN-clamp 정합($v_g$=상류 read, $u_g$=하류 write).
- **후보 사다리(ablation rung):** F0(가산)=CPA-등가 / F1(저랭크 affine)=primary / F2(게이트 변형) = F1 우위 입증 후 옵션 / F3(비선형 MLP)=합성 비폐쇄·식별성 포기, MVP 밖.

### 2.3 Gene-feature 하이퍼네트워크 $f_\phi$ (linchpin)
ID 임베딩 금지. 4계열 frozen feature를 융합:
$$ \phi_g = \big[\ \text{ESM-2 proj(256, frozen)}\ \|\ \text{GO-text LM emb + GO multi-hot}\ \|\ \text{network topo vec(node2vec, frozen)}\ \|\ \text{train-control baseline 발현/essentiality}\ \big] $$
```
concat → LayerNorm → modality-level dropout → MLP(2~3층, GELU, residual) = h_g
   ├─ U_g = reshape(W_U h_g) ∈ R^{d×r}
   ├─ V_g = reshape(W_V h_g) ∈ R^{d×r}
   ├─ b_g = W_b h_g          ∈ R^d
   └─ γ_g = σ(w_γ·h_g)       ∈ (0,1)   (gate; baseline 발현 0 → γ_g→0)
```
- **그래프 메시지패싱 금지.** GO/network는 frozen feature 벡터로만 사용 → GEARS의 over-smoothing(이웃 평균 붕괴)을 원천 차단. 유전자 간 유사도는 feature 거리로 자연발생.
- **GEARS를 (혹시) 이긴다면 그 이유 = ①target/loss(mean-MSE→분포·연산자) + ②다출처 연속 feature.** ②만으로는 불충분.
- **modality-level dropout** = 단일 feature 의존 방지 + 같은 모델로 AB5(leave-one-feature-out) 측정.
- **context FiLM은 약하게만** ($\gamma_c\odot h_g+\beta_c$, 작은 lr/강한 정규화). 주된 context 의존은 transition이 처리 → "operator=유전자 정체성, context=세포상태" 분해 보호.

### 2.4 분산-평균 분리 — panel의 fatal flaw를 정면으로 박는 핵심 설계 결정
**[FATAL FLAW, beats-baseline panel] 수학적 사실:** control 잠재가 중심화($\mathbb{E}[z]\approx 0$, 표준 VAE/PCA encoder가 강제)되면, pseudobulk 평균에 대한 곱셈항 기여는
$$ \mathbb{E}_j\big[U_g V_g^\top z^{(j)}\big] = U_g V_g^\top\,\mathbb{E}[z] \approx 0. $$
즉 **pseudobulk 평균(=PDS/DES/weighted-ΔR²가 계산되는 양)은 전적으로 $b_g$ 가 결정**하고, $b_g=f_\phi(\phi_g)$ 는 곧 feature-linear baseline($\delta_g=W\phi_g$)의 MLP판이다. state-dependent 곱셈항(=F1을 F0보다 고른 유일한 이유)은 **평균이 아니라 집단 분산/이질성(E-distance)에만** 쓰인다.

**결정 (panel fix: "pick one"에 답한다):** 곱셈항의 novelty를 **분포/이질성 주장으로 재포지셔닝**하고, **Cell B에서 PDS/DES로 additive를 이긴다는 주장을 철회**한다. 두 옵션 중 (b)를 택한다:
- (a) ✗ control 잠재를 비중심화해 $U_gV_g^\top\mathbb{E}[z]\neq0$ 으로 평균에 흘리기 → 식별성·중심화 가정 붕괴, 채택 안 함.
- (b) ✓ 곱셈항의 가치를 **E-distance + 사전등록 responder/non-responder 이질성 지표**에서만 평가. 평균 지표(PDS/DES)는 §4.2의 **결정론적 $b_g$ 경로**로 계산. → 곱셈항의 성패와 평균 지표가 명확히 분리되고, 각 주장이 자기 지표에서만 검증된다.

이 결정의 귀결: **Cell B의 1차 가설은 "전체 operator가 $b_g$-only보다 E-distance/이질성에서 CI>0로 우위"** 이며, PDS/DES에서 additive를 이긴다는 약속은 하지 않는다(§8 kill-gate가 이를 강제).

### 2.5 연산자-flow 결합 (이중계상 비판 대응)
**[CONCERN, reduces-to-existing & feasibility] "operator가 출발점·velocity 조건·drift 3곳에 들어가 표현력 있는 flow가 conditioning만으로 다 해버리면 operator는 장식"** — 이를 ablation으로 분리한다.
- 기본: **operator-as-drift (A)** — flow 기본 표류를 $z\mapsto M_g z + b_g$ 로, CFM이 잔차 경로/퍼짐만. operator가 inductive bias.
- 비교: **operator-as-conditioning (B)** — $\text{vec}(U_g,V_g,b_g)$ 를 velocity FiLM 입력으로만. **이 변형은 사실상 CFM-GP에 구조화된 conditioning 벡터일 뿐** — panel이 지적한 환원 경로. 그래서 **필수 ablation으로 등록**(§8 AB7, AB8): "operator-as-conditioning vs 자유 학습 conditioning 임베딩 at fixed flow"가 둘을 가른다.

### 2.6 Decoder $D_\phi$ — count likelihood
$$ X_{gj}\sim\mathrm{NB}\big(\mu_{gj}=\ell_j\,\mathrm{softmax}(W z_{post}^{(j)})_g,\ \theta_g\big) $$
- $\ell_j$=size factor, $\theta_g$=유전자별 dispersion. deterministic $z\to$파라미터.
- **means/pseudobulk 복원성(CLAUDE invariant #6):** pseudobulk $=\text{mean}_j\,\mu_{\cdot j}$ → PDS/DES/baseline과 완전 동일 파이프라인.
- 한계(정직): NB는 유전자 독립 가정 → gene-gene 공분산 미모델링. E-distance가 의존성을 놓치는 약점[S11]과 맞물림 → §8 미해결 #4 (copula/저랭크 공분산 헤드 필요성).

---

## 3. 학습 목적함수 & 데이터 흐름

### 3.1 control-population 조건화 (3경로)
1. **출발 분포 = control 잠재 자체 (bridge):** $z0^{(i)}=M_g z_{ctrl}^{(i)}+b_g$. 개별 control 다양성이 출발점 다양성으로 보존. ← **[panel fix]** 단, "출발점 다양성으로 인한 E-distance 우위"가 가짜 win이 될 수 있으므로 §3.4 control-diversity 베이스라인 필수.
2. **velocity 조건 $h_g$** = 연산자 요약(스파인 산출).
3. **context 풀링 $c$** = control 집단 set-summary(DeepSets/attention) + cell-line 메타. Cell C에서 RPE1 control 통계가 flow를 재타겟.

### 3.2 unpaired coupling
파괴적 시퀀싱 → control↔perturbed 비대응. 미니배치 **Sinkhorn-OT coupling**(OT-CFM/I-CFM, Departures 계열)으로 $\pi$ 매칭. 직선보간 $z_t=(1-t)z_0+t z_1$, 목표속도 $u=z_1-z_0$.

### 3.3 손실 (3중 + anti-collapse)
$$ \mathcal{L} = \underbrace{\mathcal{L}_{\text{CFM}}}_{\text{velocity regression}} + \lambda_d\,\mathcal{L}_{\text{dist}} + \lambda_r\,\mathcal{L}_{\text{NB-recon}} + \lambda_v\,\mathcal{L}_{\text{var}} + \underbrace{\lambda_U\|U_gV_g^\top\|_F^2 + \lambda_b\|b_g\|_1 + \lambda_{\text{null}}\!\!\sum_{g\in\text{null}(i)}\!\!(\|M_g-I\|_F^2+\|b_g\|^2) + \lambda_{\text{smooth}}\mathcal{L}_{\text{feat-smooth}}}_{\text{구조/식별성 정규화}} $$
- $\mathcal{L}_{\text{CFM}}=\mathbb{E}_{t,(z_0,z_1)\sim\pi}\|v_\theta(z_t,t|h_g,c)-(z_1-z_0)\|^2$. velocity-matching이라 "평균만 출력"이 전역최소가 아님.
- $\mathcal{L}_{\text{dist}}=$ geomloss energy 또는 Sinkhorn (eval과 동형, invariant #7). 잠재공간 손실 + 발현공간 eval 이중계산.
- $\mathcal{L}_{\text{var}}=\text{relu}(\tau-\text{mean}_g\,\text{Var}_j[\hat z_1|g])$ — 조건부 분산 hinge.
- $\lambda_d$ 초기 작게→ramp, $\lambda_v$ 는 collapse 감지 시만(§3.5 충돌 주의).

### 3.4 means가 어떻게 복원되는가 (deterministic 평균경로 — panel fix)
**[FIX — beats-baseline & feasibility]** 확률적 ODE 적분(MPS 5~10 step의 OT-coupling 노이즈)이 PDS의 rank discrimination을 깎는다(결정론적 baseline 대비 분산만 추가). 따라서:
- **PDS/DES/weighted-ΔR² 는 ODE 샘플 궤적이 아니라 $b_g$ + decoder로 해석적으로 계산**한 결정론적 pseudobulk에서 뽑는다(적분 노이즈 우회).
- **확률적 flow 출력은 E-distance/MMD/responder 분석에만** 사용.
- → 분포 head가 rank/DE 지표를 악화시키는 경로를 구조적으로 차단. (이것이 §2.4 결정 (b)의 구현이다.)

### 3.5 null 균형 & anti-collapse vs specificity 충돌 (사전등록 operating point)
**[CONCERN, 3 panels 공통] $\lambda_v$ 를 키워 collapse를 막으면 null에 가짜 변동을 환각해 false-positive-DE↑(specificity 실패). 두 성공기준이 단일 노브로 반대부호 gradient.**
- null(~59%)은 **기본 EVAL 전용**, 학습 주입 시 down-weight/class-balance.
- **[FIX] $\lambda_v$ 대 specificity의 operating point를 사전등록**하고, mini-data에서 **dedicated null-control set으로 anti-collapse가 false-positive-DE를 부풀리지 않음을 먼저 보인 뒤** RPE1 outcome을 연다. heterogeneity와 specificity를 **항상 동시 보고**(둘 중 하나만 좋으면 win 아님).
- **[FIX] 정규화 충돌 검증:** specificity를 주는 $\lambda$ 가 Cell B signal-gene의 $\|M_g-I\|,\|b_g\|$ 까지 항등으로 끌어내리는지 mini-data에서 측정. 같은 $\lambda$ 가 specificity와 Cell B discrimination을 동시에 죽이면 **그것을 falsification으로 보고**(둘 다 만족하는 설정이 존재한다는 증거 없음을 인정).

### 3.6 컴퓨트 (M5 Pro dev / A100 train)
- $\mathcal{O}(dr)$ 연산자, frozen ESM/LM(오프라인 precompute, 유전자당 1벡터 캐시), 학습 파라미터 수 M.
- **same code, config-only 차이**(device/d/step/batch). mini-only 알고리즘 분기 금지.
- **[FIX — feasibility panel, device parity]** geomloss는 KeOps(MPS 백엔드 없음) → Apple silicon에서 dense fallback, OT coupling은 CPU POT fallback → mini가 A100과 **다른 수치 경로**를 탈 위험. **단일 coupling/loss 코드 경로를 세 device 모두에서 돌게 고정**(예: POT/dense everywhere 또는 I-CFM fallback)하고, **device-parity 수치 테스트**(동일 fixture를 cpu/mps/cuda에서 돌려 coupling 행렬·loss·적분 $z_1$ 이 tol 내 일치) 통과를 full run 전 게이트로. MPS 실패는 은닉 말고 보고.

---

## 4. Cell B/C 승리 메커니즘 + novelty를 격리하는 ablation

### 4.1 baseline이 무너지는 지점
- **mean baseline:** 모든 g에 같은 출력 → PDS 구조적 0. (단 MAE/Pearson은 높을 수 있음 → 이래서 PDS/DES로 본다.)
- **additive / latent-additive:** $\delta_g$ 가 학습 g에서만 정의 → unseen g(Cell B)에서 정의 불가, mean으로 퇴화.
- **feature-linear ($\delta_g=W\phi_g$):** unseen g에 정의는 되나 선형·가산. **이것이 ALIVE의 진짜 경쟁자.**

### 4.2 ALIVE가 정보를 흘리는 경로 (정직 버전)
- **Cell C (1차):** "무엇을 켜고 끄는가($M_g$)는 cell-line 불변, 어디서 시작하는가($z_{ctrl}$)만 RPE1로 바뀐다." RPE1 control이 입력 context로 들어옴. **단, $b_g$(평균기여분)는 설계상 cell-line 불변 → RPE1로 옮기면 registered 'transferred-K562-effect' baseline과 동일.** RPE1로 재타겟되는 건 곱셈항 $U_gV_g^\top z_{ctrl}(\text{RPE1})$ 뿐(=분산/state 효과, 평균 불변). **그래서 Cell C 평균 win은 transferred-effect baseline을 이겨야 하고, 그 우위는 분포/이질성에서 나와야 한다**(panel 지적 그대로 인정).
- **Cell B (진단):** unseen g에 $M_g=f_\phi(\phi_g)$ 로 amortized 예측. 단 §2.4 때문에 **평균 win 약속 없음**. Cell B의 등록 가설 = "전체 operator > $b_g$-only > feature-linear, E-distance/이질성에서 CI>0".

### 4.3 ablation 사다리 (논문의 척추) — panel이 요구한 누락 ablation 추가
같은 encoder/decoder/flow 고정, 한 축만 교체. 모두 그리드 셀별 + perturbation-level bootstrap 95% CI.

| # | 축 | control | ALIVE | 입증 |
|---|---|---|---|---|
| AB1 | ID vs feature | per-gene ID $e_g$ | $\phi_g\to M_g$ | feature가 **B/D에서만** ID 우위 → 진짜 zero-shot |
| AB2 | operator vs linear | $\delta_g=W\phi_g$ | $M_g z$ 저랭크 곱셈 | operator 구조 기여 |
| AB3 | dist vs mean head | 평균 head | flow head | 분포 출력 기여 (E-dist 위주) |
| AB4 | low-rank vs full | full $M_g$ | 저랭크 $r\ll d$ | 저랭크 귀납편향 |
| AB5 | feature LOO | GO/PPI/seq/expr 각 제거 | 전체 | 어느 feature가 zero-shot 캐리 |
| AB6 | **feature shuffle (필수 sanity)** | 셔플 $\phi_g$ | 진짜 $\phi_g$ | 셔플로도 안 떨어지면 누출/암기 → 모든 zero-shot 주장 무효 |
| **AB7** | **[NEW] operator vs bias-only at fixed flow** | $b_g$-only + full flow | $I+U_gV_g^\top, b_g$ + same flow | 곱셈항이 flow가 주는 것 이상을 더하는가 — **CFM-GP-with-bias로의 환원을 가르는 결정적 ablation** |
| **AB8** | **[NEW] structured operator vs free conditioning** | 같은 feature의 비구조 임베딩으로 fixed flow conditioning | 저랭크 operator로 conditioning | plain conditional CFM과의 분리 |
| **AB9** | **[NEW] control-diversity-only baseline** | control 세포를 항등/$v=0$ 으로 통과 | full flow | E-distance 우위가 **입력 control 다양성의 공짜 spread가 아니라** flow가 학습한 조건부 spread임을 증명 |

**[FATAL FLAW, feasibility panel] AB9의 중요성:** bridge 출발점 $M_g z_{ctrl}$ 에 다양한 실제 control을 통과시키면 거의-항등 사상으로도 현실적 spread가 나와 mean baseline을 E-distance에서 이긴다 — 이는 metric-gaming(S19/S23). 따라서 **mean을 이기는 것으로는 불충분**하고, **flow가 control-diversity-only(v=0) baseline을 E-distance CI>0로 이겨야** 비로소 "분포를 학습했다"고 인정.

**핵심 2×2 교차 진단:** feature operator의 가치는 B/D에서만 ID 우위가 나야 진짜. A/C에서도 크게 이기면 zero-shot이 아니라 단순 regularization → 오귀속 차단.

---

## 5. 평가 (기존 harness 연결)

| win 메커니즘 | 1차 지표 | 게이트/방어 |
|---|---|---|
| operator-from-features (Cell B/D, 분포/이질성) | E-distance↓, responder 지표 | AB1·AB2·AB6·AB7·AB8·AB9; **PDS/DES 평균 우위 주장 안 함** |
| 분포 출력 | E-distance↓ | AB3 + **AB9(control-diversity baseline)**, self-prediction 상한, random+transform sanity |
| 저랭크 귀납편향 | B·D 강건성 | AB4 |
| context transfer (Cell C, 1차) | PDS/DES/E-dist(C셀) | strongest baseline(transferred-K562, no-change) 대비, p53 stratum 분리, encoder OOD 사전점검 |
| 평균 복원 | PDS/DES/weighted-ΔR² | **결정론적 $b_g$ 경로(§3.4)** — 적분노이즈 우회 |
| 통계적 유의 | 전 지표 | **perturbation-level bootstrap 95% CI 하한>0** (점추정 단독 금지) |
| 특이성 | false-positive-DE rate | EVAL null-control set, zero-effect는 stratum(i)만, $\lambda_v$ operating point 사전등록(§3.5) |
| 생물 타당성 | (랭킹 아님) | **bio-sanity-gate 합격/불합격만**, 리더보드 합산 금지 |

**평가 불변식:**
- 같은 생성 출력에서 평균지표(결정론 경로)와 분포지표(확률 경로)를 동시 산출.
- self-prediction 상한(Cell A, 절반→절반)을 각 셀에 표시. random+transformation이 top model보다 높으면 지표 무효 신호[S19].
- **bio-recovery는 sanity gate only.** GO/network prior를 입력받은 모델을 textbook pathway 일치로 순위화 = prior 암기를 일반화로 오인하는 순환논리 → 합격/불합격만.

**[FATAL/CONFOUNDER] p53-null(K562) vs p53-WT(RPE1):**
- 사실: K562는 TP53 null → CDKN1A(p21)/MDM2/BAX 하향 신호 부재. RPE1엔 존재.
- transfer 함의: p53 경로 연산자 방향($V$의 p53 좌표)은 K562 학습데이터에 신호 없음 → underdetermined, RPE1 transfer 불가. **"cell-line 불변 연산자" 가정이 p53 경로에서 깨진다.**
- 완화: (a) p53-의존 모듈 표적/유전자를 Cell C에서 **별도 stratum 분리 보고**(전체 점수에 미혼입). (b) transfer 1차 입증은 **p53-비의존 공유 essential 경로**에서. (c) p53 좌표에서 epistemic uncertainty가 높게 나오는지(OOD 정상작동) 확인.
- **bio-sanity-gate:** TP53→p21/MDM2/BAX 점검은 **RPE1(p53-WT)에서만** 유효. K562 단계에서는 K562에서 실제 발현·작동하는 마커로 대체(K562 TP53는 null-stratum이므로 K562 마커 금지). 마커는 null-stratum(i)(on-target KD AND 실재 downstream 반응)에 드는 표적만.
- 더 깊은 confounder: K562 vs RPE1 차이는 p53만이 아님(전체 transcriptome 배경·batch·day·endpoint 동시변동). p53는 **명명된 대표 confounder**일 뿐 → operator transfer의 "cell-line 불변" 가정은 **경로별로 검증**(invariant #8 systematic-variation 점검 후에만 신뢰).

---

## 6. 단계적 로드맵 (plan Phase 매핑)

원칙: **각 흡수(B,C)는 "새 정규화 항 + 그 강도 ablation"으로 들어오고, 강도 0 = MVP. 흡수 후 Cell C(1차)·Cell B(진단)의 bootstrap CI 하한이 흡수 전보다 나빠지면(material regression) 즉시 끈다.** B/C가 안 도우면 끄고 "MVP가 더 강함"을 결과로 보고(valid science).

### Phase 0–1 (데이터/베이스라인/하니스)
- Registered baselines 구현: mean, additive, **feature-linear($W\phi_g$)**, ID-only, **control-diversity-only(AB9)**, transferred-K562-effect, no-change.
- 평가 하니스: PDS/DES/E-dist/MMD/weighted-ΔR² + perturbation-level bootstrap CI + null-control set + self-prediction 상한 + random+transform sanity.

### Phase 2 (MVP = A 중심 + kill-gate)
- **MVP 정의:** mask=ones(GRN-clamp off), composition off(dose=1 고정, 학습 신호 없음), context-split off, identifiability penalty off.
- **kill-gate (다른 모든 것 빌드 전, §8):** "additive-shift($b_g$-only) vs 저랭크 state-dependent, 동일 feature conditioning·동일 CFM head, Cell B & Cell C, perturbation-level bootstrap CI." state-dependent가 (E-distance/이질성에서) additive를 CI 하한>0로 못 넘으면 **operator framing은 죽었고 모델은 CPA+CFM** → go/no-go.
- device-parity 수치 테스트(§3.6) + encoder OOD 사전점검(§2.1) 통과.

### Phase 3 (분포 backbone 완성)
- OT-CFM + NB decoder 정착. **Cell C 1차 합격축.** AB3/AB7/AB8/AB9 실행.

### Phase 4 (calibration / uncertainty)
- aleatoric(NB) vs population heterogeneity(flow 분산) 분리를 별도 추정자로 검증(단순 모델분산 주장 금지, invariant #10).

### Phase 5+ (흡수 단계 — primary win 보존 조건부)
- **B = GRN-clamp 기전:** $V$를 GRN 인접/pathway membership으로 graph-Laplacian 구조 정규화, knockdown 대상 clamp→downstream 전파. mechanism-path 출력(g clamp→TF 모듈→downstream DE)을 $M_g$ 활성방향에서 읽어 반환. **강도 $\lambda_{\text{GRN}}$ 0→점증 ablation 축, $\lambda_{\text{GRN}}=0$=MVP.** mechanism-path 생물타당성은 **sanity gate only**(랭킹 금지, 순환논리 방어). held-out g에서 알려진 표적 직하류 방향 회복 점검(p53 confounder 때문에 마커는 테스트 라인 기능분만).
- **C = 식별성/인과 주장:** §7 참조. **MVP에서는 "identifiability"라는 단어와 $M_g=M_g^{\text{shared}}M_C^{\text{ctx}}$ 분해를 모델 #1의 selling point에서 제거**(panel fix). 인과 주장은 (1)interventional held-out, (2)개입→latent 인자 식별성 안정성, (3)반사실 모듈성 3조건 모두 충족 시에만, **별도 split·별도 증거로**, 다중환경 단계에서.
- **dose/조합:** Tahoe(dose)·Norman(조합) 등 적정 데이터 확보 후에만 composition algebra 학습·검증. MVP에선 형식만 보존, **spine 선택 근거로 사용 금지**.

---

## 7. 리스크 & 완화 (critique 기반, 정직)

### 7.1 Fatal flaw — 처리 결과
- **F-1 novelty가 검증 불가 1개 항으로 붕괴 (state-dependent term).** → **kill-gate를 다른 모든 것 빌드 전에 실행**(§6 Phase 2, §8). 못 넘으면 CPA+CFM임을 공개 선언. [accepted risk: 통과 확률 불확실, go/no-go로 처리]
- **F-2 곱셈항이 0으로 정규화되어 CPA로 자기환원.** → 저랭크 penalty를 곱셈항이 0으로 안 눌리게 설정하고 **signal vs null perturbation의 학습된 norm을 보고**. signal도 ~0이면 "모델이 CPA로 self-reduce했다"고 보고. [§3.5, §8]
- **F-3 곱셈항은 pseudobulk 평균에 0 기여 → PDS/DES win과 분리.** → **§2.4 결정 (b):** 곱셈항을 분포/이질성 주장으로 재포지셔닝, Cell B PDS/DES 평균 우위 주장 철회, 평균은 결정론 $b_g$ 경로(§3.4). [설계에 반영, 해결]
- **F-4 novel piece에 Cell B 학습신호 0 + 정규화가 unseen g를 항등으로 끎.** → **null-anchoring/Frobenius/L1/smoothness 강도가 Cell B signal-gene을 항등으로 죽이는지 mini-data에서 측정**, 죽이면 falsification 보고(§3.5). Cell B를 진단축으로 강등(§1.3). [accepted risk + 측정 게이트]
- **F-5 분포 win이 입력 control 다양성으로 제조됨(metric-gaming).** → **AB9 control-diversity-only baseline을 registered baseline으로**, flow가 이를 E-distance CI>0로 이겨야만 인정(§4.3). [설계에 반영, 해결]

### 7.2 Serious concern — 처리 결과
- **C-1 operator 이중계상(출발점+조건+drift), flow가 conditioning만으로 다 함.** → AB7/AB8 추가(§2.5, §4.3). [해결]
- **C-2 식별성 주장 오염 (환경 2개, p53 collinear confound).** → **identifiability 단어·context-split 분해를 MVP에서 제거**(§6 Phase 5, §7.3). "제약된 가설공간 prediction surrogate"로만 표현. [수정 반영]
- **C-3 하이퍼네트워크가 ID 테이블처럼 암기(수천 유전자).** → AB1 노출 + feat-smoothness + free-ID 차단 + modality dropout. 노출만 하고 방지 보장은 못함 → [accepted risk: AB1에서 B/D 붕괴하면 linchpin 가설 약화로 정직 보고]
- **C-4 ESM의 CRISPRi 관련성 약함 → family-level 룩업(GO over-smoothing의 연속판).** → AB5로 ESM 단독 평활 진단, 다출처 융합으로 분해. [accepted risk: feature가 선형 probe 이상을 못 주면 deep premium ~0 — AB2/AB7로 정직 노출]
- **C-5 누출(baseline-expr는 cell-line별, GO/UniProt가 Replogle 결과 흡수).** → (a) baseline-expr 정규화/projection을 **RPE1에 fit 금지**(RPE1 control은 inference input으로만, 정적 import 검사로는 안 잡히므로 fit-provenance 명시 점검). (b) GO/UniProt **pre-Replogle 스냅샷 고정 + provenance 추적**, 못 거르는 annotation 비율을 known risk로 보고. (c) **AB6 셔플 테스트를 모든 feature/zero-shot 주장의 hard gate**로 — 발화 시 zero-shot 주장 전부 무효. [hard gate + 정직 보고]
- **C-6 anti-collapse hinge vs specificity 충돌(setpoint 없음).** → $\lambda_v$ operating point 사전등록 + null-control set에서 false-positive-DE 미증가 선검증, heterogeneity·specificity 동시 보고(§3.5). [해결]
- **C-7 bridge + 59% null + no-change attractor = mode-collapse 셋업.** → null EVAL 전용/down-weight, signal배치 우선, 분산 hinge, Cell A PDS 우연수준이면 발동 진단. [완화, 잔여위험 monitor]
- **C-8 Cell C가 약화된 같은 operator transfer에 의존 + encoder OOD.** → encoder batch-aware(RPE1 control only) + OOD 사전점검(§2.1). $b_g$ transfer는 transferred-effect baseline과 동일함을 인정, 곱셈항 우위로만 차별화 주장(§4.2). [수정 반영 + 정직 scope]
- **C-9 MPS Sinkhorn-OT/geomloss 수치경로가 A100과 불일치.** → 단일 코드경로 고정 + device-parity 테스트(§3.6). [해결]
- **C-10 composition algebra가 MVP에서 unfalsifiable인데 spine 선택 근거로 쓰임.** → **spine 정당화에서 composition 제거**, 단일유전자 state-dependence로만 재정당화(§1.2, §6). [수정 반영]

---

## 8. 미해결 질문 (owner 설계 결정 필요)

1. **[가장 중요] Cell B의 지위.** north-star는 "Cell B PRIMARY", plan·이 설계의 수학(§2.4)은 "Cell B를 평균지표로 이길 메커니즘이 약함 → 진단축". 기본안은 **Cell C 1차 + Cell B는 "feature_operator > feature_linear, E-distance/이질성 CI>0" 단일 가설의 falsification**. owner가 (a) 이 기본안 수용, 또는 (b) Cell B에서 분포/이질성 CI>0를 PRIMARY로 격상(높은 실패확률 수용) 중 결정해야 함.

2. **kill-gate 통과 기준의 엄격도.** state-dependent가 additive를 "어느 지표(E-distance/responder)에서, 어느 셀(B/C)에서, 몇 % CI 하한"으로 넘어야 go인가? §2.4 이후 평균지표는 제외되므로 분포/이질성 지표의 최소 효과크기를 사전등록해야 함.

3. **rank $r$ 의 최적값.** $r=1$(해석·GRN정합) vs $r=4/8$(표현력). Cell C에서 CI>0를 최초 달성하는 최소 $r$? mini-data ablation으로 결정(단 $r$ 튜닝이 RPE1 outcome을 보면 invariant #3 위반).

4. **decoder 공분산 모델링 필요성.** NB 유전자독립 + E-distance의 의존성 미포착[S11] → copula/저랭크 공분산 헤드를 Phase 3에 넣을지 Phase 4로 미룰지.

5. **operator-flow 결합 (drift A vs conditioning B).** AB7/AB8 결과에 따라 결정. drift가 inductive bias를 더 주지만 flow 자유도 제약. 분포정확도(E-dist)와 평균정확도(결정론 경로)를 동시에 잘 내는 쪽 미검.

6. **feature 구성의 zero-shot 캐리 성분.** GO vs network vs ESM seq vs baseline expr 중 무엇이 실제 기여(AB5 LOO)? baseline expr는 cell-line 의존이라 cross-line 전이를 돕거나 누출할 수 있음 — 어느 쪽인지 사전 점검 필요.

7. **encoder batch-aware 방식.** RPE1 control을 scVI batch covariate로 넣는 것이 Cell C OOD를 충분히 해소하는가, 아니면 operator 앞에 명시적 context-alignment step이 필요한가? Phase 3 이전 결정.

8. **null 학습 주입 비율 & $\lambda_v$/$\lambda_{\text{null}}$ operating point.** specificity vs sensitivity vs mode-collapse 삼각 균형. 학습 loss 주입 vs 사후보정(연산자 norm 임계) 중 무엇이 안전한가.

9. **GO/UniProt provenance 컷오프.** Replogle 결과가 annotation에 반영된 시점 특정이 어려움 — pre-2022 스냅샷으로 충분한가, 못 거르는 비율은? AB6 셔플이 최종 방어선.

---

### 부록: 한 줄 요약 (owner용)
**CFM-GP급 분포 backbone(encoder+OT-CFM+NB) 위에, CPA를 strict superset으로 nest하는 feature-conditioned 저랭크 affine 연산자를 얹는다. 검증 가능한 유일한 novelty는 state-dependent 곱셈항이며, 이는 pseudobulk 평균이 아니라 집단 분산/이질성에만 기여하므로 E-distance + control-diversity baseline 대비 CI>0로만 입증한다. 평균지표(PDS/DES)는 결정론적 bias 경로로 계산해 baseline과 정면 비교한다. 1차 목표는 Cell C(context transfer), Cell B는 falsification 축. composition algebra·identifiability·causal은 MVP 주장에서 제외하고 Phase 5+로 분리한다. 다른 모든 것을 빌드하기 전에 kill-gate(state-dependent vs additive, 동일 flow, Cell B/C, bootstrap CI)로 go/no-go를 본다.**
