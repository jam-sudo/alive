#!/usr/bin/env python
"""Pod CLI: extract fit roles -> write immutable .h5ad -> validate (A1).

Thin wrapper over ``alive.compose.fit_role``. The RunSpec/source/split assembly
that feeds real digests is the production driver's job (sub-project C); this
entry point only orchestrates the library and fails closed.
"""

from __future__ import annotations

import argparse
import sys


def build_fit_role_cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build + validate a COMPOSE fit-role artifact")
    ap.add_argument("--run-spec", required=True, help="committed RunSpec path (driver-assembled)")
    ap.add_argument(
        "--out", required=True, help="output .h5ad path under the approved artifacts root"
    )
    try:
        ap.parse_args(argv)
    except SystemExit:
        return 2
    print(
        "error: real source/split assembly is provided by the production driver "
        "(sub-project C); this A1 CLI is a library entry point only.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(build_fit_role_cli())
