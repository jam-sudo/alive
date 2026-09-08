#!/usr/bin/env python
"""Pod CLI STUB: always exits 2 and writes nothing.

Real source/split assembly is the production driver's job (sub-project C); the
dev-smoke path is scripts/compose/build_dev_smoke_payload.py.
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
