"""Frozen TG-K562-v1 base predictor as a gene-space mean-change predictor (no refit).

Decodes the preserved ridge PCA mean shift through the frozen loadings:
``h = standardized_features @ W @ components`` on the TG selected-gene axis
(normalized log1p, library size 10,000). Centering means cancel for a shift and are not
added. This reads no expression, outcome or seal; it uses only pinned bundle artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def decode_shift(shift: np.ndarray, components: np.ndarray) -> np.ndarray:
    """Map PCA-space mean shifts (n x k) to gene space (n x genes) via loadings (k x genes)."""
    return np.asarray(shift, dtype=np.float64) @ np.asarray(components, dtype=np.float64)


def main() -> None:  # pragma: no cover - real-bundle entry point
    from alive.base.predictor import BasePredictor
    from alive.data.features import FeatureBank
    from alive.data.preprocess import ResponseSpace

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--targets", type=Path, required=True, help="JSON list of target labels")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    files = json.loads((args.bundle / "bundle.json").read_text())["files"]
    for name in (
        "base.json",
        "base.npz",
        "base_predictor.json",
        "base_predictor.npz",
        "feature_bank.json",
        "feature_bank.npz",
    ):
        if hashlib.sha256((args.bundle / name).read_bytes()).hexdigest() != files[name]:
            raise ValueError(f"bundle artifact hash mismatch: {name}")
    space = ResponseSpace.read(args.bundle / "base")
    predictor = BasePredictor.read(args.bundle / "base_predictor")
    bank = FeatureBank.read(args.bundle / "feature_bank")
    targets = json.loads(args.targets.read_text())
    supported = sorted(t for t in targets if t in set(bank.genes))
    unsupported = sorted(set(targets) - set(supported))
    feats = np.stack([bank.standardized_vector(t) for t in supported])
    changes = decode_shift(
        np.stack([predictor.predicted_shift(f) for f in feats]), space.components
    )
    args.out.mkdir(parents=True, exist_ok=False)
    np.save(args.out / "predicted_change.npy", changes.astype(np.float32))
    record = {
        "estimand": "decoded ridge mean shift on TG selected genes (log1p CP10k over 8,563)",
        "gene_ids": list(space.selected_gene_ids),
        "supported": supported,
        "unsupported": unsupported,
        "fit_perturbation_ids": list(space.fit_perturbation_ids),
        "predicted_change_sha256": hashlib.sha256(
            (args.out / "predicted_change.npy").read_bytes()
        ).hexdigest(),
    }
    (args.out / "record.json").write_text(json.dumps(record, indent=1))
    print(len(supported), "supported;", len(unsupported), "unsupported")


if __name__ == "__main__":
    main()
