"""Regression checks for the production activation-evidence publication contract."""

from pathlib import Path

_ROOT = Path(__file__).parents[3]
_RUNBOOK = _ROOT / "docs/superpowers/runbooks/2026-07-02-compose-k562-pod-sealed-run.md"
_POD_PLAN = _ROOT / "docs/superpowers/plans/2026-07-09-compose-dev-pod-real-workers.md"
_BIAS_SPEC = _ROOT / "docs/superpowers/specs/2026-07-13-compose-approximation-bias-metric-design.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_production_reports_are_published_outside_the_git_worktree() -> None:
    runbook = _read(_RUNBOOK)
    plan = _read(_POD_PLAN)

    assert "ACTIVATION_EVIDENCE_STAGE" in runbook
    assert "FINAL_CONFIG_PATH" in runbook
    assert "repository root 밖" in runbook
    assert "$ACTIVATION_EVIDENCE_STAGE/real_norman_phi_rank_report.json" in runbook
    assert "$ACTIVATION_EVIDENCE_STAGE/real_norman_detectable_effect_report.json" in runbook

    forbidden_outputs = (
        "--out docs/activation-evidence/compose/real_norman_phi_rank_report.json",
        "--out docs/activation-evidence/compose/real_norman_detectable_effect_report.json",
    )
    for forbidden in forbidden_outputs:
        assert forbidden not in plan


def test_post_generation_commit_self_reference_is_forbidden() -> None:
    runbook = _read(_RUNBOOK)
    plan = _read(_POD_PLAN)
    bias_spec = _read(_BIAS_SPEC)

    assert "마지막 commit" in runbook
    assert "fixed point" in plan
    assert "Do not make a post-`C` READY commit" in plan
    assert "Do not edit/commit the basis config after commit `C`" in bias_spec
    assert "DERIVE externally" in bias_spec
