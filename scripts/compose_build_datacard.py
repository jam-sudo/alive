#!/usr/bin/env python
"""Finalize the COMPOSE-K562-v1 Norman data-card + raw SHA-256 (§10.1 blocker).

Thin CLI over :func:`alive.compose.datacard.build_data_card`. It derives the
obs/var schema and the control/single/double counts DIRECTLY from the processed
Norman ``.h5ad`` (backed read mode, safe on the full ~666 MB asset), records the
file's SHA-256 as the raw/source digest, and writes a deterministic, committable
data-card JSON. Source-level metadata (DOI, license, cell line, modality,
perturbation column, control token, combo separator) is read from the activated
COMPOSE config so the card cannot drift from the pre-registration.

This opens NO seal and reads NO outcomes — it records dataset metadata + hashes
only. It is the ``finalized_norman_data_card_and_sha256`` activation deliverable;
the resulting ``processed_sha256`` / ``raw_or_source.digest`` feed the composite
``run_id`` (spec §10.6).

Usage
-----
    uv run python scripts/compose_build_datacard.py \
        --config configs/compose_k562_v1_phase2.yaml \
        --h5ad ~/ALIVE-data/norman/NormanWeissman2019_filtered.h5ad \
        --out docs/data-cards/norman_compose_k562_v1.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from alive.compose.datacard import build_data_card

#: Immutable source-publication metadata not carried in the config `data:` block.
_SOURCE_DOI = "10.5281/zenodo.13350497"
_PROCESSING_VERSION = "scPerturb-NormanWeissman2019_filtered"


def _load_data_block(config_path: Path) -> dict:
    """Return the ``data:`` block of the COMPOSE config."""
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "data" not in raw:
        raise SystemExit(f"config {config_path} has no 'data' block")
    return raw["data"]


def main(argv: list[str] | None = None) -> int:
    """Build and write the finalized Norman data-card."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--h5ad", required=True, type=Path, help="processed Norman .h5ad")
    ap.add_argument("--out", required=True, type=Path, help="data-card JSON destination")
    args = ap.parse_args(argv)

    h5ad = args.h5ad.expanduser()
    if not h5ad.exists():
        raise SystemExit(f"processed h5ad not found: {h5ad}")

    data = _load_data_block(args.config)
    card = build_data_card(
        processed_h5ad=h5ad,
        raw_asset=h5ad,  # the scPerturb filtered file is the canonical held asset
        source_uri=str(data["source"]),
        source_doi=_SOURCE_DOI,
        license=str(data["license"]),
        cell_line=str(data["cell_line"]),
        modality=str(data["modality"]),
        processing_version=_PROCESSING_VERSION,
        perturbation_col=str(data["perturbation_key"]),
        control_token=str(data["control_token"]),
        combo_sep=str(data["combo_sep"]),
    )

    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(card, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"wrote data-card -> {out}")
    print(f"  processed_sha256      = {card['processed_sha256']}")
    print(f"  raw_or_source.kind    = {card['raw_or_source']['kind']}")
    print(f"  raw_or_source.digest  = {card['raw_or_source']['digest']}")
    print(f"  counts                = {card['counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
