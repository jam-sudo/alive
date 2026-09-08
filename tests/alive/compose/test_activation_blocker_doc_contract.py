"""Every document that enumerates activation blockers matches the loader.

An external audit (`docs.blocker-count-contract-stale`) found the readiness index
claiming "five" explicit activation blockers while its own parenthetical read as
seven and the loader measured six. Correcting the prose was not enough twice
over:

1. The first correction reached the runbook and the readiness index and **missed
   the decision document** -- the recurring sibling-slot omission. The sweep that
   was supposed to catch that used the pattern ``five activation`` and the actual
   string was ``five explicit activation blockers``. A sweep with an
   over-specific pattern is not a sweep.
2. The count was right at six but the SPELLING was wrong. The enumeration was
   written by reading the YAML and reasoning about which nulls "count", when
   ``ComposePhase2Config.activation_blockers`` -- the component that defines the
   contract -- was available the whole time. It emits ONE collective
   ``baselines.approximation_bias_report_sha256`` while any approximate
   representation lacks its bias report, not a per-method key.

So the number is pinned to the measurement instead of to prose discipline. The
approach and the CPA-exactness reasoning come from an independent external fix of
the same finding (2026-08-23), which pinned the decision document; this extends
the same contract to every sibling that carries the enumeration, which is the
half that fix was missing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alive.compose.config2 import load_compose_phase2_config

_ROOT = Path(__file__).parents[3]
_CANON = _ROOT / "configs/compose_k562_v1_phase2.yaml"

#: Documents that enumerate the blockers, with the count token each one writes.
#: ``strict`` marks the ones whose whole text must avoid the per-method bias
#: spelling; the runbook legitimately names that config FIELD elsewhere (it is
#: the single leaf a pod trip edits), so only its enumeration is pinned.
#: The count is asserted as the EXACT enumeration phrase, whitespace-normalised,
#: never as a bare token. A bare ``"six"`` passed even after the enumeration was
#: edited to say "five", because the readiness index says "six" in three
#: unrelated sentences -- the assertion could not fail, which is the same
#: vacuity this contract exists to prevent.
_DOCS = (
    (
        "docs/superpowers/2026-08-17-compose-ablation-ladder-decisions.md",
        "still carries **six** explicit activation blockers",
        True,
    ),
    (
        "docs/superpowers/COMPOSE-SEAL-READINESS.md",
        "still carries **six** activation blockers",
        True,
    ),
    (
        "docs/superpowers/runbooks/2026-07-02-compose-k562-pod-sealed-run.md",
        "activation blocker **여섯**이 그대로 남아 있고",
        False,
    ),
)

_PER_METHOD = (
    "`baselines.gears.approximation_bias_report_sha256`",
    "`baselines.cpa.approximation_bias_report_sha256`",
)


@pytest.mark.parametrize(
    ("relative", "count_token", "strict"), _DOCS, ids=[d[0].split("/")[-1] for d in _DOCS]
)
def test_documented_blockers_match_the_loader(
    relative: str, count_token: str, strict: bool
) -> None:
    cfg = load_compose_phase2_config(_CANON)
    text = (_ROOT / relative).read_text(encoding="utf-8")

    # 2026-08-29: this used to `pytest.skip` when the document did not carry the
    # committed digest -- and the standing audit finding
    # `tests.activation-blocker-contract-skips-on-config-change` said that turns
    # green precisely when the check is most needed. It was demonstrated live: the
    # pair-dependence decision moved the digest and this contract silently skipped
    # on the readiness index. Every document in `_DOCS` is CURRENT state, so a
    # missing digest means stale, not exempt. If one ever becomes history, it moves
    # to an explicit archive roster pinned to its own digest -- it does not get to
    # opt out by drifting.
    assert cfg.config_sha256[:8] in text, (
        f"{relative} enumerates activation blockers but does not carry the committed "
        f"config digest {cfg.config_sha256[:8]!r}; a current document must track the "
        "live config lineage"
    )

    blockers = cfg.activation_blockers
    assert len(blockers) == 6, "fixture assumption: the loader measures six blockers today"
    for key in blockers:
        assert f"`{key}`" in text, f"measured blocker `{key}` is not enumerated verbatim"
    normalized = " ".join(text.split())
    assert count_token in normalized, (
        f"the document does not state the measured count in its enumeration: {count_token!r}"
    )

    # The loader's collective key is the contract; a per-method spelling misstates
    # it and would let the CPA null read as a blocker, which it is not -- CPA's
    # representation is exact (`cell_raw_counts`).
    assert "baselines.approximation_bias_report_sha256" in blockers
    if strict:
        for per_method in _PER_METHOD:
            assert per_method not in text, f"{per_method} misstates the collective loader key"


def test_the_contract_would_notice_a_wrong_count() -> None:
    """Non-vacuity. If the loader's list and the documents could not disagree,
    the assertions above would pass no matter what the prose said."""
    cfg = load_compose_phase2_config(_CANON)
    text = (_ROOT / _DOCS[0][0]).read_text(encoding="utf-8")
    assert "five explicit activation blockers" not in text, (
        "the pre-correction wording is still present; the contract above would be asserting "
        "against text that contradicts it"
    )
    assert any(f"`{k}`" in text for k in cfg.activation_blockers)
