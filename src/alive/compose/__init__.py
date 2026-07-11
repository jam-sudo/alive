"""COMPOSE-K562-v1 — identifiable interaction-composition operator (Phase 1).

Phase 1 = synthetic identifiability/recovery proof + Norman pre-check gates.
No seal access; see docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md.

Public re-exports of the Phase-1 API are exposed **lazily** (PEP 562): importing
the package binds no submodule until an attribute is first accessed. This keeps
the deep-baseline subprocess workers — which import only the pure-python contract
modules (``baseline_subprocess`` / ``fit_role`` / ``response``) under a minimal
locked science env — from transitively pulling the full Phase-1 stack (config →
``yaml``, gates, identify, phase1, synthetic) that the isolated env does not carry.
"""

from __future__ import annotations

import importlib

# attribute name -> submodule that defines it (imported on first access only).
_LAZY_EXPORTS: dict[str, str] = {
    "ComposePhase1Config": "alive.compose.config",
    "ConfigError": "alive.compose.config",
    "load_compose_config": "alive.compose.config",
    "GateResult": "alive.compose.gates",
    "LeakageError": "alive.compose.gates",
    "measurability_gate": "alive.compose.gates",
    "power_gate": "alive.compose.gates",
    "rank_gate": "alive.compose.gates",
    "RankReport": "alive.compose.identify",
    "identify_operator": "alive.compose.identify",
    "rank_diagnostics": "alive.compose.identify",
    "Phase1Report": "alive.compose.phase1",
    "run_phase1": "alive.compose.phase1",
    "write_phase1": "alive.compose.phase1",
    "write_phase1_provenance": "alive.compose.phase1",
    "AliasMap": "alive.compose.gene_universe",
    "GeneUniverseError": "alive.compose.gene_universe",
    "GearsGeneRosterArtifact": "alive.compose.gene_universe",
    "MandatoryReport": "alive.compose.gene_universe",
    "assert_gears_roster_matches": "alive.compose.gene_universe",
    "compute_mandatory_report": "alive.compose.gene_universe",
    "generate_gears_gene_roster": "alive.compose.gene_universe",
    "load_gears_gene_roster": "alive.compose.gene_universe",
    "normalize_full_then_subset": "alive.compose.gene_universe",
    "RecoveryReport": "alive.compose.synthetic",
    "frontier_sweep": "alive.compose.synthetic",
    "run_recovery": "alive.compose.synthetic",
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> object:
    """Lazily resolve a re-exported Phase-1 symbol (PEP 562)."""
    module = _LAZY_EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(module), name)


def __dir__() -> list[str]:
    """Return ordinary module globals together with unresolved lazy exports."""
    return sorted(set(globals()) | set(__all__))
