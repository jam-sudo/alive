"""COMPOSE-K562-v1 — identifiable interaction-composition operator (Phase 1).

Phase 1 = synthetic identifiability/recovery proof + Norman pre-check gates.
No seal access; see docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md.

Public re-exports of the Phase-1 API for convenience.
"""

from __future__ import annotations

from alive.compose.config import ComposePhase1Config, ConfigError, load_compose_config
from alive.compose.gates import (
    GateResult,
    LeakageError,
    measurability_gate,
    power_gate,
    rank_gate,
)
from alive.compose.identify import RankReport, identify_operator, rank_diagnostics
from alive.compose.phase1 import (
    Phase1Report,
    run_phase1,
    write_phase1,
    write_phase1_provenance,
)
from alive.compose.synthetic import RecoveryReport, frontier_sweep, run_recovery

__all__ = [
    "ComposePhase1Config",
    "ConfigError",
    "load_compose_config",
    "GateResult",
    "LeakageError",
    "measurability_gate",
    "power_gate",
    "rank_gate",
    "RankReport",
    "identify_operator",
    "rank_diagnostics",
    "Phase1Report",
    "run_phase1",
    "write_phase1",
    "write_phase1_provenance",
    "RecoveryReport",
    "frontier_sweep",
    "run_recovery",
]
