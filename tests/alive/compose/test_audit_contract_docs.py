"""Doc-contracts for the 2026-09-07 audit-debate remediation.

These pin STRUCTURE (a pending decision must carry NO-GO; a signed decision must carry its
sentence), never the owner's choice. A pending decision is a valid state, not a failing test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_DECISIONS = Path("docs/superpowers/2026-09-07-compose-audit-release-decisions.md")
_MAIN_SPEC = Path("docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md")
_READINESS = Path("docs/superpowers/COMPOSE-SEAL-READINESS.md")


def _section(text: str, head: str, next_head: str | None) -> str:
    body = text.split(f"## {head}", 1)[1]
    return body.split(f"## {next_head}", 1)[0] if next_head else body


@pytest.mark.parametrize(
    "head,next_head", [("D1", "D2"), ("D2", "D3"), ("D3", "D4"), ("D4", "Amendment")]
)
def test_every_pending_decision_is_marked_no_go(head, next_head):
    sec = _section(_DECISIONS.read_text(encoding="utf-8"), head, next_head)
    assert "status:" in sec and "release:" in sec
    if "status: PENDING" in sec or "status: DEFER" in sec:
        assert "release: NO-GO" in sec
