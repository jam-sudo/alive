#!/usr/bin/env python
"""Record cloud-run operational provenance next to a run's artifacts (§14.2).

The :class:`~alive.provenance.RunLedger` already captures the Git SHA, lockfile
hash, dependencies, and input hashes.  This thin recorder adds the cloud-specific
metadata §14.2 asks for — instance / GPU, lockfile hash, wall time, and cost —
to ``<run_dir>/cloud_run.json`` so the ephemeral instance is not the only record.

Usage
-----
    uv run python scripts/record_cloud_provenance.py \
        --run-id "$RUN_ID" --artifacts-root ./artifacts \
        --instance-type a100-40gb-x1 --wall-seconds 5400 --cost-usd 12.50 \
        --notes "full K562 essential run"
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
from pathlib import Path

from alive.provenance import sha256_file


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _gpu_info() -> dict:
    try:
        import torch  # noqa: PLC0415

        if torch.cuda.is_available():
            return {
                "cuda": torch.version.cuda,
                "torch": torch.__version__,
                "devices": [
                    torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())
                ],
            }
        return {"cuda": None, "torch": torch.__version__, "devices": []}
    except Exception:  # noqa: BLE001
        return {"cuda": None, "torch": None, "devices": []}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Record cloud-run provenance (§14.2).")
    p.add_argument("--run-id", required=True)
    p.add_argument("--artifacts-root", type=Path, default=Path("./artifacts"))
    p.add_argument("--instance-type", default="unknown")
    p.add_argument("--wall-seconds", type=float, default=None)
    p.add_argument("--cost-usd", type=float, default=None)
    p.add_argument("--lockfile", type=Path, default=Path("uv.lock"))
    p.add_argument("--notes", default="")
    args = p.parse_args(argv)

    run_dir = args.artifacts_root / "cartographer" / args.run_id
    if not run_dir.exists():
        print(f"error: run dir {run_dir} not found", flush=True)
        return 2

    record = {
        "run_id": args.run_id,
        "git_sha": _git_sha(),
        "instance_type": args.instance_type,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "gpu": _gpu_info(),
        "lockfile_sha256": sha256_file(args.lockfile) if args.lockfile.exists() else None,
        "wall_seconds": args.wall_seconds,
        "cost_usd": args.cost_usd,
        "notes": args.notes,
    }
    out = run_dir / "cloud_run.json"
    out.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {out}")
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
