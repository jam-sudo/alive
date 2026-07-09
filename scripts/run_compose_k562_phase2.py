#!/usr/bin/env python
"""COMPOSE-K562-v1 production driver CLI — thin shim (Task 11).

All argparse wiring, dispatch and exit-code mapping lives in
``alive.compose.driver.cli.main`` (CLAUDE.md §7: production logic in ``src/``,
scripts stay thin and only call library functions). See
docs/superpowers/specs/2026-07-07-compose-production-driver-design.md §1.1.
"""

from __future__ import annotations

from alive.compose.driver.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
