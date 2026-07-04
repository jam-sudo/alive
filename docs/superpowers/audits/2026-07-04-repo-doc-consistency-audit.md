# Repo Documentation Consistency & Record-Quality Audit

> **일자:** 2026-07-04
> **범위:** documentation-record consistency + code-quality/record hygiene. **과학적 타당성 평가 아님.**
> **방법:** 4개 cluster를 병렬 audit(governance+vision · specs · plans+runbooks · configs+evidence) 후
> load-bearing 주장(git SHA·file 존재·hard number·test count·git remote)을 직접 재검증.
> **대상:** tracked docs 중심. `.superpowers/sdd/`(gitignore된 process scratch)와 branch
> `loop-engineering-local`의 loop-harness 코드는 범위 외로 처리하고, untracked/local-only 항목은 표시함.

---

## 0. 총평 (headline)

레포 문서는 **load-bearing 축에서 사실적으로 건전하다.** specs·plans·configs·evidence 전반에서 참조되는
모든 file/config/module/SHA/number가 실제로 존재하고 상호 정합적이다(직접 재검증). fabricated reference,
broken provenance, TBD/placeholder는 없다. evidence JSON의 hard number(regime 41+22+68=131, k=4/6/8 →
rank 10/21/36, condition 15.8/32.9/484.2, data SHA, dependency pin)는 모두 cross-reconcile된다. compose
test suite는 `.venv`에서 **645 clean collect**된다.

결함은 사실상 **한 부류**다 — **stale status framing.** 2026-06-30 COMPOSE activation과 TG-K562 sealed
run 완료 이후의 세계 상태를 여러 문서가 아직 반영하지 못했다. activation edit는 `CLAUDE.md` header/§4/§16과
config/spec의 status field는 갱신했지만, (a) `CLAUDE.md`의 서술적 "current MVP" framing(§1/§3.1), (b)
entry-point `README.md`, (c) `A100-real-run-runbook.md`, (d) pre-activation vision 문서·GPT-audit
snapshot에는 전파되지 않았다. 이는 CLAUDE.md governance가 경고하는 "duplication → drift" 실패양상 그
자체다.

---

## 1. HIGH — 즉시 수정 권장 (3)

| # | 위치 | 문제 | 수정 |
|---|------|------|------|
| **H1** | `CLAUDE.md` §1 Mission ("현재 활성 MVP는 **K562 retrospective CARTOGRAPHER Trust-Gate**다") | 같은 파일 header(활성=`COMPOSE-K562-v1`)·§4.1(TG=COMPLETE)·§4.2(COMPOSE=ACTIVE)·§16과 **정면 모순.** load-bearing Mission 절이 완료된 protocol을 현재 MVP로 명명. | Mission을 COMPOSE-K562-v1(Norman CRISPRa 비가산 epistasis operator) 활성으로 서술, CARTOGRAPHER는 COMPLETE 선행 milestone으로. **→ 제안된 재작성본이 해결.** |
| **H2** | `README.md` — title "ALIVE — **CARTOGRAPHER Trust-Gate MVP**" + 본문 (line 6–7, §evaluate-once) | entry-point 문서가 CARTOGRAPHER를 현재/유일 프로젝트로 제시. TG-K562 COMPLETE도, sealed run이 이미 1회 열려 **NO_DISTINCT_WIN**을 냈다는 사실도, COMPOSE ACTIVE도 언급 없음. "single audited access to the sealed cohort"를 미래형으로 서술(seal은 이미 소진). | 상단 status banner: TG-K562-v1 COMPLETE(NO_DISTINCT_WIN, seal 1회 소진); COMPOSE-K562-v1 ACTIVE(A100 sealed run pending). README가 (완료된) CARTOGRAPHER pipeline mechanics 문서임을 명시. |
| **H3** | `docs/A100-real-run-runbook.md` — header(line 3 "decisive K562 scientific run") + Step 0(line 28 "There is currently **no git remote**") | 두 개의 stale fact. (1) TG-K562 decisive run은 이미 실행·완료(NO_DISTINCT_WIN)인데 status banner 없이 현재 운영 계약처럼 읽힘. (2) **git remote가 실제로 존재** — `origin → github.com/jam-sudo/alive.git`(PR #5–#8 merged). 독자가 두 stale 문장에 따라 재실행하거나 `gh repo create`를 수행할 위험. | status banner("TG-K562-v1 COMPLETE — 실행됨, NO_DISTINCT_WIN; provenance 보존용, 재실행 금지") 추가. Step 0을 기존 `origin` remote 반영하도록 수정. |

*H3 직접 검증:* `git remote -v` → `origin https://github.com/jam-sudo/alive.git`. `git rev-parse main` → `62a2bd4`.

---

## 2. MED — stale/ambiguous/duplication

### 2.1 `CLAUDE.md` 내부 (모두 **제안 재작성본이 해결**)
- **§3.1** ("현재 CARTOGRAPHER protocol의 문서") — 활성 milestone spec pointer가 CARTOGRAPHER를 가리킴. COMPOSE spec/config로 갱신 필요.
- **§4.2** — 활성 config를 "**candidate** Phase-2 config"로 지칭. 같은 절이 ACTIVE 선언 + config 파일은 `status: active`. 내부 불일치. ("activated Phase-2 config"로).
- **§12 layout** — 활성 protocol의 코드가 있는 `src/alive/compose/`와 top-level module(`cli.py`/`config.py`/`io.py`/`provenance.py`/`types.py`)이 누락. (`loop/`는 untracked local-only이므로 tracked 문서에서 제외 유지.)
- **§8.1 "Current" / §9.1 "현재"** — COMPLETE인 TG-K562를 "current/현재"로 표현.
- **개정일 2026-06-30** — activation edit가 §1/§3.1까지 전파되지 않은 미완 revision의 증상.

### 2.2 Vision trio (pre-activation planning 문서)
- `virtual-cell-project-plan.md`(작성 2026-06-19) / `virtual-cell-research-report.md`(2026-06-19) — now-DEFERRED K562→RPE1 축을 primary MVP("1차 합격 목표")로 제시, COMPOSE·완료된 TG 언급 없음. → dated "superseded / historical planning doc" note + CLAUDE.md §4 registry 링크.

### 2.3 Specs (`docs/superpowers/specs/`)
- **deep-baselines** (`2026-07-01-…-design.md`) — §0.B/§0.C가 `phase2b.py`의 `TODO(activation)`/미배선 상태를 서술하나, 현재 `phase2b.py`엔 `TODO(activation)` **없음**(구현 완료). 설계본(`b7c1384`)은 PR #5(`c324b33`, 2026-07-02 merged)의 조상 → 이미 merge됨. status "DRAFT… owner 검토 대기"도 stale. → IMPLEMENTED/superseded-by-PR#5로 표기.
- **compose-epistasis** (`2026-06-22-…-design.md`) —
  - dangling in-doc `§N` refs: §2.4 "§14.2", §4.4 "§13.5", §5 "§15" — 문서 내 해소 안 됨(spec 최대 §10). CLAUDE.md ref면 prefix 필요, §14.2는 CLAUDE.md에서도 "A100"이라 오지정.
  - **"591 green"** test count(§10.1) — 현재 `tests/alive/compose` = **645** collected(전체 1330). activation snapshot이면 "591 at activation commit d507a09"로 고정, 아니면 refresh.
- **alive-model1** (`2026-06-20-…-design.md`) — CLAUDE.md §4 registry에 없고 어떤 active spec도 참조 안 하는 orphan 설계(memory상 핵심 capability가 non-novel로 판명 → COMPOSE pivot 유발). "superseded/historical" marker 및 revision date 부재. → status pointer + COMPOSE/CT-RPE1 cross-link.
- **filename-date vs revision-date:** cartographer(`2026-06-20-…`, 개정일 06-21, 내용은 06-22 확정run 포함 → 개정일 06-22로); fit-data(`2026-07-02-…`, 개정일 07-03).
- **fit-data §0** — "PR #7이 aggregate-only 재구현(경로 B)을 삭제" 표현. PR #7(`8321af3`) diff는 runbook markdown 25줄만 수정 — 코드 "재구현" 삭제 아님. "runbook §2.1(PR #7)이 contract 수준에서 aggregate-only를 strike"로 완화.

### 2.4 Plans / configs
- **phase1 plan** (`2026-06-23-…`) — 내장 config schema(`lambda_grid`, `false_gi_tol`)가 live `configs/compose_k562_v1_phase1.yaml`·`phase1.py`(λ hard-coded, ratio margin `_FALSE_GI_RATIO_MARGIN`)와 drift. plan대로 loader 재현 시 현재 config를 reject. → schema 갱신 또는 post-merge 진화 note.
- **phase1 config + plan "DEFERRED" comment** — `configs/compose_k562_v1_phase1.yaml` line 1 + phase1 plan line 202. protocol은 ACTIVE(2026-06-30)이고 이 config는 activation blocker(`real_norman_detectable_effect_report.json`의 `phase1_config_sha256`) 생성에 실제로 소비됨. "DEFERRED"는 ambiguous. → "Phase-1 gates가 activation pre-check에 소비됨; standalone Phase-1 sealed run만 DEFERRED"로.
- **phase2a plan** (`2026-06-24-…`) — header "Status: ACTIVE (2026-06-30 activation)"인데 body §1이 아직 "Real execution remains forbidden until `CLAUDE.md`가 ACTIVE로 commit될 때까지". body에 activation 통과(2026-06-30) 반영. (phase2b도 동일 패턴 약하게.)
- **pod sealed-run runbook** (`2026-07-02-…`) — "코드 기준점 `c324b33` 이상"은 PR #5. 이후 PR #6/#7/#8 merge로 main HEAD=`62a2bd4`(runbook §2.1이 의존하는 fit-role artifact 포함). floor를 current main으로 상향 + A1/A2가 해소한 §2 blocker 표기. (runbook은 여전히 정당하게 BLOCKED: worker/driver/durable-ledger = sub-project B/C/D 미구현, `scripts/run_compose_k562_phase2.py` 부재 확인.)
- **GPT-audit 2종 + REMEDIATION_PLAN** — `docs/GPT audit/*`(2026-06-21)와 `claude_science/REMEDIATION_PLAN.md`(base `c324b33`)는 activation·payload-v2 작업에 의해 overtaken된 point-in-time snapshot. dated SUPERSEDED banner 권장. (둘 다 날짜·read-only framing이 있어 snapshot으로 읽히긴 함. `claude_science/`는 **untracked**.)

---

## 3. LOW — record hygiene

- **detectable_effect JSON** (`real_norman_detectable_effect_report.json` L50–51) — `sealed_single_unseen.recommendation`이 "double-unseen adequately powered as headline"로 double-unseen 문구를 copy-paste. single-unseen(n=68)은 registered SECONDARY. → "single-unseen meets power floor as registered secondary."
- **data-card** (`norman_compose_k562_v1.json`) — `processed_sha256` == `raw_or_source.digest`(동일 hash). processed 산출물 존재 여부가 under-specified. → 별도 processed digest 기록 또는 raw==processed임을 명시.
- **activation-evidence README** (L44) — "measurability floor 0.2"가 prose에만 존재, JSON `measurability` block엔 threshold field 없음(ceiling 0.9176/passed만). → JSON에 floor 추가.
- **compose-epistasis spec** — `[[alive-operator-design-incremental]]` 등 `[[memory-slug]]` wiki-link(§0/§3.1/§4.5/§4.6)가 private auto-memory를 가리켜 committed markdown에서 dangling. → 일반 citation/실제 경로로 변환 또는 제거.
- **pod runbook §7 vs provenance plan** — §7.3 `phase2b_pre_access_ledger.json`(durable file, sub-project D 지연) vs plan의 ledger key `phase2b_pre_access_provenance`(`PRE_ACCESS_PROVENANCE_ARTIFACT`, in-ledger). 개념은 다르나 near-identical 이름이 혼동 유발. → disambiguate.
- **cartographer-mvp plan** — filename 06-20 / "Revision 2026-06-21". cosmetic.

---

## 4. Local-only / expected (결함 아님)

- **loop-harness 문서** (`2026-06-30-{loop-engineering,science-dev-profile,spec-review-profile}` plans + specs) — `src/alive/loop/*`, `configs/loop_profiles.yaml`, `scripts/loop_gate.py`, `docs/superpowers/loop/*` 참조가 현재 branch(`compose-payload-v2`)엔 부재. 이들은 branch `loop-engineering-local`에만 존재하며 문서가 스스로 "LOCAL ONLY, 미커밋"으로 선언 → 자기 scope와 정합. **untracked.** science-dev plan의 "13개 Tier-0 test 경로 존재(확인됨)"는 정확(13개 모두 present).
- **REMEDIATION_PLAN의 `[POD-ONLY]` 부재 파일** (`run_compose_k562_phase2.py`, `gears_worker.py`, `cpa_worker.py`) — 명시적으로 "미구현 3종"으로 문서화된 gap → broken reference 아님.

---

## 5. 검증되어 건전한 항목 (참고)

- **artifact 존재:** CLAUDE.md §4.2·specs·plans·runbooks가 참조하는 모든 code/config/evidence/data-card 파일 존재(`src/alive/compose/{outcome_store,terminal,provenance2,phase2b,baselines_combo,fit_role,...}.py`, 4개 config, activation-evidence 3종, data-card).
- **git SHA:** specs/plans/evidence가 인용한 SHA 전부 존재(`8b47901 a2f3d8f 9f9f3aa a040665 e50f7c8 2146dac 90e7f06 2dd3f65 8321af3 c324b33 d507a09 c9c3f6b 62a2bd4 82a9c83 79b01e0 b7c1384 …`).
- **line-ref:** `response.py:107`(def project), `baselines_combo.py:203`(`_assert_no_sealed_reference`), `phase1.py:60`(`_FALSE_GI_RATIO_MARGIN`) 정확.
- **number reconciliation:** regime 131, k-rank 10/21/36, condition number, cells 111445/control 11855/singles 105, data/manifest/sequence SHA, dependency pin(gears 74/cpa 115), Zenodo DOI `10.5281/zenodo.13350497` — 모두 config/data-card/README/evidence 간 일치.
- **test suite:** `.venv`에서 `tests/alive/compose` = 645 clean collect(전체 1330). (system-python 호출 시의 33 collection error는 audit 도구 invocation artifact — 레포 결함 아님.)
- **seal 안전:** COMPOSE seal이 열렸다고 주장하는 문서 **없음** — 모두 one-time sealed run을 별도 pending A100 step으로 일관 서술(canonical facts와 정합).
- **markdown:** prose에 TBD/FIXME/XXX 없음, code fence balanced.

---

## 6. Root cause & 권고 패턴

단일 구조적 원인: **2026-06-30 activation이 status field는 flip했으나 서술적 framing에는 전파되지 않았다.**
동일 사실(activation date, 6 blocker, opens-once, A100+ActivationRecord)이 ~5곳에 중복되어 drift 위험을 만든다.

권고:
1. **Live governance(`CLAUDE.md`, `README.md`)** → status framing 직접 수정.
2. **Point-in-time 문서(GPT audit, REMEDIATION_PLAN, vision trio, model1 spec, A100 runbook의 TG 부분)** →
   재작성 대신 **dated SUPERSEDED banner**(과거 기록 보존 + 오독 방지).
3. **CLAUDE.md 재작성 제안**(`docs/superpowers/specs/2026-07-04-CLAUDE-md-proposed.md`)이 §1.1의 CLAUDE.md
   internal 항목을 해소하고, 5x 중복된 activation 사실을 단일 canonical 문장으로 접어 향후 drift를 줄인다.

*이 audit는 assessment다. 어떤 파일도 수정하지 않았다(`CLAUDE.md`는 ARS-guarded). 수정 적용은 owner 승인 후.*

---

## 7. 적용 가능성 self-review & 위험성 판단 (2026-07-04)

**결론: "다 적용"은 안 된다.** finding은 진짜지만, 순진하게 적용하면 provenance/hash chain을 깨는 항목이
있다. 3분류: **① 안전(in-place) · ② 편집금지(note로만) · ③ 재검토(as-is 적용 불가).**

### 7.1 Showstopper 위험 (직접 검증)

- **R1 — CLAUDE.md 재작성본의 renumbering이 75개 `CLAUDE.md §N` 참조를 깬다.**
  code 41개(`src/`,`scripts/`,`tests/`) + tracked docs 34개 = **75개**가 현재 numbering에 hard-key돼 있다.
  제안본은 safety-first로 재배치하며 renumber → dangling을 넘어 **오지정**이 발생:
  - 현재 §5(invariants) → 제안 §5는 Protocol registry. `datacard.py:12` "CLAUDE.md §5"가 registry를 가리키게 됨.
  - 현재 §7(data) → 제안 §7은 Repository/compute. `datacard.py` "§5, §7"이 오지정.
  - 현재 §6(seal)·§11(immutability) → 제안 §6은 data/eval, §11 없음. `phase2b.py:1088` "§6 / §11", `cli.py`의 다수 "§11"이 dangling.
  provenance guard 코드가 자기 governing rule을 가리키는 traceability가 깨진다. **⇒ full renumber restructure는 as-is 적용 불가.** (CLAUDE.md 편집 자체는 hash에 안 들어가 안전 — 문제는 오직 renumbering.)

- **R2 — activation-evidence 파일 편집은 sealed-run gate를 깬다.**
  `ActivationRecord.evidence_files`는 각 evidence 파일의 **bytes가 `evidence_hashes`와 scientific boundary에서 일치**해야 함(`config2.py:354–359`). `real_norman_detectable_effect_report.json`의 copy-paste label(LOW), data-card digest(LOW) 등을 **파일 편집으로 고치면 byte-hash가 바뀌어 A100 sealed run이 거부/무효**가 될 수 있다. **⇒ `docs/activation-evidence/*`·data-card는 편집 금지. erratum note로만.**

### 7.2 기타 provenance 위험

- **R3 — config field 편집 = new run identity.** evidence hash는 `sha256_json(yaml.safe_load(config))` — **comment-only 편집은 hash 무관(안전)**, 그러나 어떤 field라도 바꾸면 `config_sha256` 변경. phase1 "DEFERRED"는 comment이므로 편집해도 안전하나, 저가치.
- **R4 — spec/plan 파일 rename 금지.** filename이 곳곳에서 참조됨(§5 표, code, plans). 날짜 불일치는 **파일명 유지 + header 개정일만** 조정.
- **R5 — merged PR을 governing한 spec은 rewrite보다 additive note.** git history가 PR 시점 내용을 보존하므로 status note/banner는 안전, 본문 rewrite는 traceability 저하.
- **R6 — COMPOSE active + sealed run pending 중 governance 변경.** CLAUDE.md invariant 문구는 **정확히 보존**해야 함(sealed-run 계약이 CLAUDE.md 절을 참조). 의미 drift는 cosmetic이 아니라 scientific-integrity 위험.
- **R7 — CLAUDE.md은 ARS-guarded** → owner가 적용. 231줄 통짜 교체는 targeted diff보다 review가 어렵다 → 최소 diff 선호.

### 7.3 적용 판정

| 항목 | 판정 | 방식 / 위험 |
|---|---|---|
| H1 CLAUDE.md §1 Mission staleness | **①APPLY** | in-place targeted, numbering 보존. 고가치·저위험. owner 적용. |
| H2 README status banner | **①APPLY** | additive banner + framing. tracked, 저위험. |
| H3 A100 runbook TG-banner + remote 수정 | **①APPLY** | additive banner + 사실 수정(remote 존재 검증). 저위험. |
| CLAUDE.md-internal MED (§3.1,§4.2 candidate,§12 layout,§8.1/§9.1,개정일) | **①APPLY** | in-place, **renumber 금지**. 문구 보존(R6). |
| vision trio / GPT-audit / REMEDIATION_PLAN superseded banner | **①APPLY** | additive dated banner. 저위험(R5). claude_science는 untracked. |
| deep-baselines spec IMPLEMENTED note · alive-model1 superseded marker · phase2a "forbidden" note · pod runbook baseline 갱신 · phase1 plan schema note | **①APPLY(note)** | additive status note. 본문 rewrite 금지(R5). |
| compose-epistasis dangling §14.2/§13.5/§15 + [[wiki-link]] · "591 green"→"591 at d507a09" freeze · filename↔개정일 | **①APPLY(주의)** | 소correction. §ref는 **현재** CLAUDE.md 번호로(=renumber 안 함 전제). 591은 refresh 말고 freeze. 파일 rename 금지(R4). |
| phase1 config "DEFERRED" comment | **①APPLY(optional, comment-only)** | hash-safe이나 저가치·defensible. skip 무방. |
| evidence JSON label/digest/floor (LOW) | **②편집금지** | R2. erratum note로만, 파일 미편집. |
| **CLAUDE.md 통짜 restructure(제안본 as-is)** | **③재검토** | R1(75 refs) 때문에 as-is 불가. 아래 3안 중 택. |

### 7.4 CLAUDE.md restructure — 3가지 안전 경로

1. **In-place staleness fix만(권장, 최저위험).** 16-section skeleton·번호 유지, H1+§1.1 CLAUDE.md-internal 항목만 수정. 모순 전부 해소, 75 refs 무손상. 길이 축소는 포기.
2. **Numbering-preserving tightening(중간).** 기존 16개 절 번호·의미 유지한 채 절 *내부* 중복/장황만 압축. refs 안전 + 길이 일부 축소. (제안본은 reorder했으므로 rework 필요.)
3. **Full restructure + 75 refs 동시 갱신(고노력·고위험).** 제안본 채택하되 같은 change-set에서 code/spec의 `§N` 참조 전부 갱신 + test 재실행. 별도 tracked PR로만.

**권고:** 지금은 **경로 1** + H2/H3 banner + evidence는 erratum-note. 길이/best-practice 최적화는 경로 2/3로 별도 진행.
