"""COMPOSE-K562-v1 single production driver (sub-project C).

Thin verify-and-assemble orchestration around the existing Phase-2 library
entry points. This package hosts the immutable ``ResolvedRunSpec`` schema and
its fail-closed loader (the driver's trust boundary), the fixture builder, the
``phase2a``/``preflight``/``phase2b``/``recover`` subcommands, and the single
committed CLI entry point (``main``) that argparse-dispatches to them and maps
their results/exceptions to process exit codes (Task 11).

See docs/superpowers/specs/2026-07-07-compose-production-driver-design.md.
"""

from __future__ import annotations

from alive.compose.driver.cli import main
from alive.compose.driver.phase2a_cmd import run_phase2a_subcommand
from alive.compose.driver.phase2b_cmd import run_phase2b_subcommand
from alive.compose.driver.preflight_cmd import run_preflight_subcommand
from alive.compose.driver.recover_cmd import run_recover_subcommand

__all__ = [
    "main",
    "run_phase2a_subcommand",
    "run_preflight_subcommand",
    "run_phase2b_subcommand",
    "run_recover_subcommand",
]
