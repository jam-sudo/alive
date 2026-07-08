"""COMPOSE-K562-v1 single production driver (sub-project C).

Thin verify-and-assemble orchestration around the existing Phase-2 library
entry points. This package hosts the immutable ``ResolvedRunSpec`` schema and
its fail-closed loader (the driver's trust boundary); later tasks add the
fixture builder and the ``phase2a``/``preflight``/``phase2b``/``recover``
subcommands.

See docs/superpowers/specs/2026-07-07-compose-production-driver-design.md.
"""

from __future__ import annotations
