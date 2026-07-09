# CLAUDE.md — owner patch pack (path 1: in-place staleness fixes, numbering preserved)

> **⚠ SUPERSEDED (2026-07-08) — 미적용/폐기.** 이 패치팩은 "section 번호 보존" 전제의 in-place 수정안이나,
> 실제 `CLAUDE.md`는 이후 16→9 section(#anchor 기반)으로 재구성됐다. 아래 `count==1` 패치는 현재 파일에
> 적용되지 않으며 역사적 기록으로만 보존한다. 현재 governance는 `CLAUDE.md`(§1–§9)가 authoritative.
>
> **적용 방법:** `CLAUDE.md`는 agent Edit-guarded이므로 owner가 아래 python을 paste-run한 뒤 `git diff`
> 검토 → commit(또는 `--amend`)한다. 각 replace는 `count == 1` assert로 보호되어 원문과 정확히
> 일치하지 않으면 아무것도 바꾸지 않고 멈춘다.
>
> **안전 근거:** (1) section **번호를 바꾸지 않는다** → code 41개 + docs 34개 = 75개 `CLAUDE.md §N`
> 참조 무손상. (2) `CLAUDE.md`는 어떤 hash/provenance에도 들어가지 않는다(코드에는 docstring 인용만).
> (3) config/evidence 파일은 건드리지 않는다. (4) invariant 문구는 보존, staleness만 수정.
>
> 이 6개 패치가 `CLAUDE.md`에 대한 **전체** 변경이다.

## 무엇을 고치나 (6 patches)

| # | 위치 | 변경 |
|---|------|------|
| 0 | header 개정일 | `2026-06-30` → `2026-07-04` |
| 1 | §1 Mission (**HIGH H1**) | "현재 활성 MVP는 CARTOGRAPHER Trust-Gate" → 활성 protocol = `COMPOSE-K562-v1`, `TG-K562-v1`은 COMPLETE(`NO_DISTINCT_WIN`) |
| 2 | §3.1 | 활성-milestone spec pointer를 CARTOGRAPHER → `COMPOSE-K562-v1`; 완료된 TG 문서는 §4.1로 이동 |
| 3 | §4.2 | "candidate Phase-2 config" → "activated … (`status: active`)" |
| 4 | §8.1 | 제목 "Current K562 Trust-Gate" → "`TG-K562-v1` Trust-Gate (COMPLETE)"; 본문 "현재" 제거 |
| 5 | §9.1 | "현재 comparator family" → "TG-K562-v1 comparator family" |
| 6 | §12 layout | `src/alive/compose/`(ACTIVE) + top-level module 추가 (`loop/`는 untracked local-only이라 제외) |

## paste-run 스크립트

```python
from pathlib import Path

p = Path("CLAUDE.md")
s = p.read_text(encoding="utf-8")

PATCHES = [
    # 0 — 개정일
    ("개정일",
     "> **개정일:** 2026-06-30",
     "> **개정일:** 2026-07-04"),

    # 1 — §1 Mission (HIGH H1)
    ("§1 Mission",
     "현재 활성 MVP는 **K562 retrospective CARTOGRAPHER Trust-Gate**다. Frozen additive\n"
     "perturbation-response surrogate 위에서:\n"
     "\n"
     "1. scalar global prediction-error bound를 calibration하고,\n"
     "2. held-out K562 perturbation을 PREDICT/ABSTAIN 순서로 routing한다.\n"
     "\n"
     "현재 MVP를 mechanistic, causal, temporally resolved, clinically predictive, distribution-valued\n"
     "prediction-set model 또는 Active Cartographer라고 부르지 않는다.",
     "현재 활성 protocol은 **`COMPOSE-K562-v1`**다(ACTIVE, 2026-06-30 activation) — Norman K562 CRISPRa\n"
     "조합 perturbation에서 단일-gene signature로 고정한 factor로 transcriptome-valued 비가산 성분을\n"
     "식별가능한 bilinear operator로 예측한다(§4.2). 선행 **`TG-K562-v1`**(K562 retrospective CARTOGRAPHER\n"
     "Trust-Gate; frozen additive surrogate 위 scalar prediction-error bound + PREDICT/ABSTAIN routing)은\n"
     "COMPLETE이며 sealed verdict는 `NO_DISTINCT_WIN`이다(§4.1).\n"
     "\n"
     "현재 결과를 mechanistic, causal, temporally resolved, clinically predictive, distribution-valued\n"
     "prediction-set model 또는 Active Cartographer라고 부르지 않는다."),

    # 2a — §3.1 claim-domain pointer
    ("§3.1 claim pointer",
     "scientific claim의 정의는 해당 milestone spec(현재 CARTOGRAPHER spec §0)이 최상위다.",
     "scientific claim의 정의는 해당 milestone spec(현재 활성 `COMPOSE-K562-v1` spec §0)이 최상위다."),

    # 2b — §3.1 current-protocol document list
    ("§3.1 doc list",
     "현재 CARTOGRAPHER protocol의 문서는 다음과 같다.\n"
     "\n"
     "- Scientific spec:\n"
     "  `docs/superpowers/specs/2026-06-20-cartographer-design.md`\n"
     "- Implementation plan:\n"
     "  `docs/superpowers/plans/2026-06-20-cartographer-mvp.md`\n"
     "- Config:\n"
     "  `configs/cartographer_trust_gate_k562_v1.yaml`",
     "현재 활성 protocol(`COMPOSE-K562-v1`)의 문서는 다음과 같다(§4.2).\n"
     "\n"
     "- Scientific spec:\n"
     "  `docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md`\n"
     "- Config:\n"
     "  `configs/compose_k562_v1_phase2.yaml`\n"
     "\n"
     "완료된 `TG-K562-v1`(CARTOGRAPHER) 문서는 §4.1이 가리킨다:\n"
     "`docs/superpowers/specs/2026-06-20-cartographer-design.md`,\n"
     "`docs/superpowers/plans/2026-06-20-cartographer-mvp.md`,\n"
     "`configs/cartographer_trust_gate_k562_v1.yaml`."),

    # 3 — §4.2 candidate -> activated
    ("§4.2 candidate config",
     "Scientific claim contract와 candidate Phase-2 config는 다음에 있다.\n"
     "\n"
     "- Spec: `docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md`\n"
     "- Candidate config: `configs/compose_k562_v1_phase2.yaml`",
     "Scientific claim contract와 activated Phase-2 config는 다음에 있다.\n"
     "\n"
     "- Spec: `docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md`\n"
     "- Config (activated, `status: active`): `configs/compose_k562_v1_phase2.yaml`"),

    # 4a — §8.1 title
    ("§8.1 title",
     "### 8.1 Current K562 Trust-Gate",
     "### 8.1 `TG-K562-v1` Trust-Gate (COMPLETE)"),

    # 4b — §8.1 body "현재"
    ("§8.1 body",
     "현재 TG-K562 base는 ESM target feature와 additive population-shift predictor를 사용한다.",
     "TG-K562 base는 ESM target feature와 additive population-shift predictor를 사용한다."),

    # 5 — §9.1 body "현재"
    ("§9.1 body",
     "현재 comparator family는 CARTOGRAPHER spec/config에 등록한다. 최소한 다음 범주를 포함한다.",
     "TG-K562-v1 comparator family는 CARTOGRAPHER spec/config에 등록한다. 최소한 다음 범주를 포함한다."),

    # 6 — §12 layout: add compose/ + top-level modules
    ("§12 layout",
     "src/alive/base/         frozen base predictors\n"
     "src/alive/gate/         Trust-Gate components\n"
     "src/alive/baselines/    registered UQ/error baselines\n"
     "src/alive/conformal/    scalar calibration artifacts\n"
     "src/alive/metrics/      distance and selective metrics\n"
     "src/alive/eval/         bootstrap, verdict, reports\n"
     "src/alive/experiment/   staged development and evaluation\n"
     "configs/                immutable experiment configurations",
     "src/alive/base/         frozen base predictors (TG-K562)\n"
     "src/alive/gate/         Trust-Gate components (TG-K562)\n"
     "src/alive/baselines/    registered UQ/error baselines\n"
     "src/alive/conformal/    scalar calibration artifacts\n"
     "src/alive/metrics/      distance and selective metrics\n"
     "src/alive/eval/         bootstrap, verdict, reports\n"
     "src/alive/experiment/   staged development and evaluation\n"
     "src/alive/compose/      COMPOSE outcome store, terminal state machine, provenance2 (ACTIVE)\n"
     "src/alive/*.py          top-level: cli.py config.py io.py provenance.py types.py\n"
     "configs/                immutable experiment configurations"),
]

for label, old, new in PATCHES:
    n = s.count(old)
    assert n == 1, f"[{label}] expected exactly 1 match, found {n} — aborting, no changes written."
    s = s.replace(old, new)

p.write_text(s, encoding="utf-8")
print("applied", len(PATCHES), "patches to CLAUDE.md — review `git diff`")
```

## 적용 후 확인
- `git diff CLAUDE.md` — 위 6개 영역만 바뀌었는지, 번호 변경 없는지.
- `grep -c 'CLAUDE.md §' src -r` 등 §N 참조는 손대지 않았으므로 재검증 불필요(번호 불변).
- 길이/best-practice 최적화(제안 재작성본 `docs/superpowers/specs/2026-07-04-CLAUDE-md-proposed.md`)는
  path 2/3로 별도 진행 — 그때는 75개 §N 참조 동시 갱신 필요.
