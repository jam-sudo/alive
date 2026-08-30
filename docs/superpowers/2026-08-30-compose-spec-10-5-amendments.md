# COMPOSE-K562-v1 — three spec sentences awaiting signature

> **On the filename.** It says `spec-10-5` because the first two amendments live in
> `specs/2026-06-22-compose-epistasis-operator-design.md` §10.5. §5 adds a third, in the
> **driver** design spec. The file was not renamed: a document's identity is its path, and
> renaming it a day after it was committed costs more than a narrow name does. The content is
> what it says here.

> **STATUS: PROPOSED — owner signature required.** Both sentences describe things the repository
> already does; neither changes the estimator, the comparator family, the margins, the multiplicity
> correction, or any verdict threshold. What is missing is that the SPEC does not say them, and the
> spec is the claim contract.
>
> **Neither moves `config_sha256`.** Both are prose in `specs/2026-06-22-compose-epistasis-operator-design.md`
> §10.5. Amendment B additionally decides WHERE an already-implemented report is emitted, which is
> the one thing here with an implementation consequence — recorded in §3.

**Owner sign-off — ______________________ (name / date).**

---

## 1. Why these are separate from the decisions that produced them

Both arose from adjudications the owner has already settled, and in both cases the settlement landed
in code, config and readiness but **not in the spec**. The daily reviewer named the gap precisely for
the first one: *"materialize MAY repeat" 는 readiness 제안 인용뿐, spec 미서명* — a Medium residual
that stays open until §10.5 says it.

Putting them in one document is deliberate: they are two sentences in the same section, and the
second one's placement question is only answerable once the first is settled.

## 2. Amendment A — the consumption boundary is the claim

**Finding:** `seal.claim-materialization-replay` (adjudicated 2026-08-28, commit `91616d5`).
Reproduced exactly: one durable claim can be materialised repeatedly, sequentially or concurrently,
while the audit holds a single record. Every way that could matter is closed — the payload selector
is authenticated, a second claim is refused under any `run_id`, concurrent claims have one winner,
production materialises once, and the bytes come from a descriptor-pinned, digest-verified source.
The residual was that nothing said which of the two operations the phrase "opened exactly once"
counts.

**Proposed sentence, to follow the bootstrap paragraph in §10.5:**

> sealed cohort의 *소비*는 `claim_sealed_access`가 수행한다. 이 호출은 어떤 row도 materialise하기
> 전에 durable audit record를 먼저 기록하므로, materialisation 도중 crash가 나도 audit path는
> 소진된다. `materialize_claimed`는 멱등이며 하나의 claim에 대해 두 번 이상 호출될 수 있다.
> 따라서 등록된 access count는 materialisation이 아니라 **claim**을 센다. 내어준 bytes의 identity는
> audit record가 아니라 run의 `processed_sha256`과 descriptor로 고정된 sealed source가 함께
> 보증한다.

**What signing this does not do.** It does not authorise repeated materialisation as a practice —
production calls it once and a test pins that. It states which operation the count refers to, so the
sentence "the seal is opened exactly once" is unambiguous rather than reader-dependent.

## 3. Amendment B — the coverage claim is conditional, and where the sensitivity is reported

**Decision:** pair dependence, approved 2026-08-29
(`2026-08-29-compose-pair-dependence-decision.md`). The config already carries
`inference.simultaneous_coverage_claim` and `inference.sensitivity_band_inflation`, loader-enforced.
`inference2.band_sensitivity` already computes the report and is verified against the real
`sealed_verdict`. Two things are still unsaid.

**Proposed sentence, to follow the verdict list in §10.5:**

> 위 simultaneous coverage 주장은 등록된 resampling unit(`perturbation_pair`) 가정 **아래에서만**
> 성립한다. headline `sealed_double_unseen`은 22 pairs를 21 genes에서 뽑으므로 유전자를 하나도
> 공유하지 않는 pair가 없고, 연결성분이 둘(19, 3)이라 의존성을 흡수하는 재표본 단위가 존재하지
> 않는다. verdict는 언제나 등록된 밴드($\lambda=1.0$)에서 판정하며, 등록된
> `inference.sensitivity_band_inflation` 사다리의 각 $\lambda$에서의 lower bound와 comparator별
> 뒤집힘 지점을 **descriptive-only**로 함께 보고한다. 이 sensitivity는 어떤 경우에도 verdict
> gate가 아니다.

**The placement question this settles.** `Phase2bResult.result_checksum` is a registered composition
(spec §2.1) over exactly five components. The sensitivity is descriptive-only, so it must **not**
enter that composition — putting it there would make a descriptive report part of the run's
registered identity, which is the opposite of what the decision says. The proposal is therefore:

- the sensitivity is computed in the sealed run from the same `bounds` the verdict used, and
- it is carried on the result and written into the **report** payload, **outside** the five
  components of `result_checksum`, with its own checksum for tamper-evidence.

This is the only part of either amendment with an implementation consequence, and it is held until
signature precisely because "where a result is recorded" is a spec question, not a coding preference.

## 4. What both amendments deliberately leave open

Neither states the true magnitude of the method-differential gene effect in Norman — it is
unmeasured and needs Phase-2a dev outcomes on `combo_calibration`. Amendment B reports the verdict at
each registered $\lambda$ *because* that magnitude is unknown; it does not assert a value for it.

Neither closes the remaining pre-seal path bindings (`data_card_path`, `feature_bank_path`), which
are a separate question recorded in the readiness index.

---

## 5. Amendment C — preflight's registered stdout, adjudicated against the runbook

**Finding:** `driver.preflight-output-contract`. **CONFIRMED as a fact.**
`specs/2026-07-07-compose-production-driver-design.md` §3.2 ends with
*"화면에는 canonical payload와 full checksum을 출력한다"*, and
`driver/preflight_cmd.py` contains **no `print` at all** — it installs the write-once manifest and
returns an exit code.

**But the audit's two options are not equally right, and measuring the runbook decides it.** The
execution contract is explicit that the flow is file-mediated *by design*:

> ⚑ `--confirm-seal`에 넣는 값은 `<run_id>`가 아니다. `preflight`가 성공 시
> `<run_dir>/seal_confirmation_manifest.json`을 write-once로 설치하며 … **두 번째 운영자가
> manifest를 대조한 후**, 거기 적힌 정확한 `confirmation_checksum` 값을 `--confirm-seal`에 입력한다.

That is a **two-operator control whose medium is the artifact**. CLAUDE.md §1 ranks the
runbook above a design spec for execution contracts, and "print to screen" is an operator-UX
contract, not a scientific claim. It also sits badly with the CLI's own stdout discipline: dumping
the full canonical payload — ordered seal-request checksums, pair counts — onto a terminal makes a
screen transcript look like a record of a two-person reconciliation that is supposed to happen
against the file.

**So the implementation is right and the SPEC SENTENCE is the defect.** Adding deterministic stdout
(the audit's option a) would make the code match a sentence that contradicts the operating procedure.

**Proposed replacement for that sentence in `2026-07-07-compose-production-driver-design.md` §3.2:**

> `confirmation_checksum`은 자신을 제외한 payload의 `sha256_json`이다. payload는 화면이 아니라
> write-once manifest 파일로만 남긴다 — 확인은 runbook §6의 2인 통제대로 그 파일을 대조해 수행하며,
> `preflight`는 stdout에 아무것도 쓰지 않는다.

**Why this needs a signature rather than an edit.** The sentence being removed is in an
owner-approved design spec, and removing a "print this" requirement is exactly the kind of change
that should not be made by whoever finds it inconvenient — even when, as here, the evidence says the
requirement was the mistake.
