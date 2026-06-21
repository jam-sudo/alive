#!/usr/bin/env python
"""ESM-2 real-model forward smoke test (A100, spec §4.3 / §11.3 Gate C).

This is the one remaining real-run precondition: prove the *real* ESM-2 encoder
loads on the GPU and produces finite, correctly-dimensioned embeddings under the
config's batching + long-sequence policy — BEFORE building the full feature bank.

Thin CLI over :class:`alive.data.features.Esm2Encoder` + :mod:`alive.data.smoke`.
It requires the ``features`` extra (``uv sync --extra features``) and a GPU for
practical throughput.

Usage
-----
    # smoke-test the REAL target proteins that will go into the feature bank
    uv run python scripts/esm_smoke.py \
        --config configs/cartographer_trust_gate_k562_v1.yaml \
        --sequences data/k562_gene_sequences.json --n 16

    # or a couple of built-in canonical sequences (no JSON yet)
    uv run python scripts/esm_smoke.py --config configs/cartographer_trust_gate_k562_v1.yaml

Exit code 0 = smoke OK (finite, expected dim); 2 = failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from alive.config import load_config
from alive.data.features import Esm2Encoder
from alive.data.smoke import check_pooled, mean_pool

# Canonical short human proteins (ubiquitin P0CG48; preproinsulin P01308) — used
# only when no real sequences are supplied, to exercise the forward pass.
_DEFAULT_SEQUENCES: list[str] = [
    "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG",
    "MALWMRLLPLLALLALWGPDPAAAFVNQHLCGSHLVEALYLVCGERGFFYTPKTRREAEDLQVGQVELGGGPGAGSLQPLALEGSLQKRGIVEQCCTSICSLYQLENYCN",
]


def _model_name_from_primary(primary: str) -> str:
    """``esm2_t33_650M_UR50D_mean_pool`` -> ``esm2_t33_650M_UR50D``."""
    for suffix in ("_mean_pool",):
        if primary.endswith(suffix):
            return primary[: -len(suffix)]
    return primary


def _load_sequences(args) -> list[str]:
    if args.sequences:
        mapping = json.loads(Path(args.sequences).read_text(encoding="utf-8"))
        usable = [seqs[0] for seqs in mapping.values() if isinstance(seqs, list) and len(seqs) == 1]
        if not usable:
            print("error: no usable (exactly-one-sequence) genes in the JSON", file=sys.stderr)
            raise SystemExit(2)
        return usable[: args.n]
    if args.fasta:
        seqs, cur = [], []
        for line in Path(args.fasta).read_text(encoding="utf-8").splitlines():
            if line.startswith(">"):
                if cur:
                    seqs.append("".join(cur))
                    cur = []
            else:
                cur.append(line.strip())
        if cur:
            seqs.append("".join(cur))
        return seqs[: args.n]
    return _DEFAULT_SEQUENCES


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ESM-2 real-model forward smoke test (A100).")
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--sequences", type=Path, help="gene->[protein_seq] JSON (real targets)")
    p.add_argument("--fasta", type=Path, help="alternative: a FASTA of sequences")
    p.add_argument("--n", type=int, default=16, help="number of sequences to encode")
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    fe = cfg.feature_extraction
    model_name = _model_name_from_primary(cfg.perturbation_features.primary)
    seqs = _load_sequences(args)
    lengths = [len(s) for s in seqs]
    print(
        f"model: {model_name}  policy: {fe.long_sequence_policy}  "
        f"max_residues: {fe.max_residues}  max_batch_tokens: {fe.max_batch_tokens}"
    )
    print(f"encoding {len(seqs)} sequences (residues min={min(lengths)} max={max(lengths)})")

    encoder = Esm2Encoder(
        model_name=model_name,
        max_residues=fe.max_residues,
        long_sequence_policy=fe.long_sequence_policy,
        max_batch_tokens=fe.max_batch_tokens,
    )

    t0 = time.perf_counter()
    residues = encoder.encode_residues(seqs)
    pooled = mean_pool(residues)
    dt = time.perf_counter() - t0

    rep = check_pooled(pooled, expected_dim=encoder.dim)
    print(
        f"\nresult: n={rep.n} dim={rep.dim} (expected {rep.expected_dim}) "
        f"dim_ok={rep.dim_ok} all_finite={rep.all_finite} "
        f"range=[{rep.vmin:.3f}, {rep.vmax:.3f}]  wall={dt:.1f}s"
    )

    try:
        import torch  # noqa: PLC0415

        if torch.cuda.is_available():
            peak = torch.cuda.max_memory_allocated() / 1e9
            print(f"GPU peak memory: {peak:.2f} GB on {torch.cuda.get_device_name(0)}")
        else:
            print("WARNING: torch.cuda not available — ran on CPU (full build needs GPU).")
    except Exception:  # noqa: BLE001
        pass

    if rep.ok:
        print("\nSMOKE OK — real ESM-2 forward verified. Gate C (spec §4.3) satisfied.")
        return 0
    print("\nSMOKE FAILED — do not proceed to the full feature-bank build.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
