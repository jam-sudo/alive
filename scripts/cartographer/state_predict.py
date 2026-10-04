"""Frozen Arc State (ST-HVG-Replogle fewshot/k562 final.ckpt) inference adapter.

Design contract: follow-up draft, "State inference adapter contract" (2026-09-25).
Pure logic below imports only NumPy so it is testable in the ALIVE environment; ``main``
imports torch/state lazily and runs only in the isolated State runtime. The adapter
consumes control cells of the ``C_input`` role only and never reads perturbed cells.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Callable

import numpy as np

SET_SIZE = 64  # checkpoint cell_set_len
N_BATCH_TOKENS = 56  # checkpoint batch_dim
CONTROL_LABEL = "non-targeting"

PredictFn = Callable[[np.ndarray, int, int], np.ndarray]


def model_scale(counts: np.ndarray, columns: list[int]) -> np.ndarray:
    """Return ``log1p(1e4 * counts / row depth)`` restricted to ``columns``.

    Parameters
    ----------
    counts : numpy.ndarray
        Raw UMI counts, cells x full source gene axis (the depth denominator).
    columns : list of int
        Source-axis columns of the checkpoint's ordered HVGs.

    Returns
    -------
    numpy.ndarray
        Model-scale expression, cells x len(columns).
    """
    depth = counts.sum(1, keepdims=True)
    if np.any(depth <= 0):
        raise ValueError("zero-depth cell in control input")
    return np.log1p(1e4 * counts / depth)[:, columns]


def require_input_role(rows: np.ndarray, manifest: dict) -> None:
    """Fail unless every row belongs to the frozen ``C_input`` control role."""
    allowed = set(manifest["roles"]["C_input"])
    if not set(rows.tolist()) <= allowed:
        raise ValueError("rows outside the C_input control role")


def control_sets(n_cells: int, n_sets: int, set_size: int, seed: int) -> np.ndarray:
    """Draw ``n_sets`` disjoint index sets of ``set_size`` cells with a fixed seed."""
    if n_sets * set_size > n_cells:
        raise ValueError("not enough cells for disjoint control sets")
    return (
        np.random.default_rng(seed)
        .permutation(n_cells)[: n_sets * set_size]
        .reshape(n_sets, set_size)
    )


def predicted_change(
    predict: PredictFn, ctrl: np.ndarray, pert_index: int, n_batch_tokens: int = N_BATCH_TOKENS
) -> tuple[np.ndarray, dict]:
    """Batch-marginalized predicted mean change for one perturbation.

    Parameters
    ----------
    predict : callable
        ``predict(ctrl_sets, pert_index, batch_index) -> predicted cells`` with the shape
        of ``ctrl_sets`` (sets x cells x genes), on the model scale.
    ctrl : numpy.ndarray
        Fixed control sets (sets x cells x genes), identical for every query.
    pert_index : int
        One-hot index of the perturbation.
    n_batch_tokens : int
        Every token is used with equal weight (uniform marginalization).

    Returns
    -------
    tuple
        Mean predicted change (genes) and diagnostics: per-token and per-set changes.
        Their spread is a diagnostic, not a calibrated uncertainty.
    """
    base = ctrl.mean(axis=1)  # sets x genes
    per = np.stack(
        [predict(ctrl, pert_index, b).mean(axis=1) - base for b in range(n_batch_tokens)]
    )
    return per.mean(axis=(0, 1)), {
        "per_token_change": per.mean(axis=1),
        "per_set_change": per.mean(axis=0),
    }


def anchored_change(
    predict: PredictFn,
    ctrl: np.ndarray,
    pert_index: int,
    control_index: int,
    n_batch_tokens: int = N_BATCH_TOKENS,
    base: tuple[np.ndarray, dict] | None = None,
) -> tuple[np.ndarray, dict]:
    """Predicted effect relative to the model's own non-targeting prediction.

    Each batch token and control set is contrasted with the same token and set under the
    control perturbation, cancelling perturbation-independent model/batch offsets
    (non-targeting sanity check, 2026-09-27). ``unanchored_change`` is kept as a diagnostic.
    ``base`` may pass the precomputed ``predicted_change`` for ``control_index``.
    """
    change, diag = predicted_change(predict, ctrl, pert_index, n_batch_tokens)
    base, base_diag = base or predicted_change(predict, ctrl, control_index, n_batch_tokens)
    return change - base, {
        "per_token_change": diag["per_token_change"] - base_diag["per_token_change"],
        "per_set_change": diag["per_set_change"] - base_diag["per_set_change"],
        "unanchored_change": change,
    }


def resolve_queries(
    names: list[str], pert_index: dict[str, int]
) -> tuple[list[tuple[str, int]], list[str]]:
    """Split query targets into supported (sorted, with index) and unsupported names."""
    supported = sorted((n, pert_index[n]) for n in names if n in pert_index and n != CONTROL_LABEL)
    unsupported = sorted(n for n in names if n not in pert_index)
    return supported, unsupported


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:  # pragma: no cover - runs only in the isolated State runtime
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True, help="JSON run spec with pinned inputs")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text())
    for key, digest in spec["sha256"].items():
        if _sha256(Path(spec["paths"][key])) != digest:
            raise ValueError(f"input hash mismatch: {key}")

    import torch
    from state.tx.models.state_transition import StateTransitionPerturbationModel

    ck = torch.load(spec["paths"]["checkpoint"], map_location="cpu", weights_only=True)
    model = StateTransitionPerturbationModel(**ck["hyper_parameters"])
    model.load_state_dict(ck["state_dict"], strict=True)
    model.eval()
    device = torch.device(spec.get("device", "cpu"))
    model.to(device)

    rows = np.load(spec["paths"]["control_rows"])
    manifest = json.loads(Path(spec["paths"]["role_manifest"]).read_text())
    input_rows = np.array(sorted(manifest["roles"]["C_input"]))
    require_input_role(input_rows, manifest)
    position = {int(r): i for i, r in enumerate(rows.tolist())}
    X = np.load(spec["paths"]["control_matrix"], mmap_mode="r")
    counts = np.asarray(X[[position[int(r)] for r in input_rows]], dtype=np.float64)
    ctrl_all = model_scale(counts, spec["hvg_columns"]).astype(np.float32)
    sets = control_sets(len(ctrl_all), spec["n_sets"], SET_SIZE, spec["seed"])
    ctrl = ctrl_all[sets]  # sets x cells x genes

    pert_index = json.loads(Path(spec["paths"]["pert_index"]).read_text())
    supported, unsupported = resolve_queries(spec["queries"], pert_index)
    pert_dim = len(pert_index)
    ctrl_t = torch.tensor(ctrl, device=device)
    n_sets, n_cells, n_genes = ctrl.shape

    def predict(_ctrl, p, b):
        pert = torch.zeros(n_sets * n_cells, pert_dim, device=device)
        pert[:, p] = 1.0
        batch = {
            "ctrl_cell_emb": ctrl_t.reshape(-1, n_genes),
            "pert_emb": pert,
            "batch": torch.full((n_sets * n_cells,), b, dtype=torch.long, device=device),
        }
        with torch.no_grad():
            return model(batch, padded=True).reshape(n_sets, n_cells, n_genes).float().cpu().numpy()

    args.out.mkdir(parents=True, exist_ok=False)
    control_index = pert_index[CONTROL_LABEL]
    control_base = predicted_change(predict, ctrl, control_index)
    changes = np.zeros((len(supported), n_genes), dtype=np.float32)
    unanchored = np.zeros((len(supported), n_genes), dtype=np.float32)
    token_sd = np.zeros((len(supported), n_genes), dtype=np.float32)
    set_sd = np.zeros((len(supported), n_genes), dtype=np.float32)
    for i, (_, p) in enumerate(supported):
        change, diag = anchored_change(predict, ctrl, p, control_index, base=control_base)
        unanchored[i] = diag["unanchored_change"]
        changes[i], token_sd[i], set_sd[i] = (
            change,
            diag["per_token_change"].std(0),
            diag["per_set_change"].std(0),
        )
    np.save(args.out / "predicted_change.npy", changes)
    np.save(args.out / "per_token_sd.npy", token_sd)
    np.save(args.out / "per_set_sd.npy", set_sd)
    np.save(args.out / "unanchored_change.npy", unanchored)
    np.save(args.out / "control_unanchored_change.npy", control_base[0].astype(np.float32))
    record = {
        "estimand": "anchored: mean pred(p) - mean pred(non-targeting), same sets and tokens",
        "spec_sha256": _sha256(args.spec),
        "supported": [n for n, _ in supported],
        "unsupported": unsupported,
        "n_sets": n_sets,
        "set_size": n_cells,
        "n_batch_tokens": N_BATCH_TOKENS,
        "device": str(device),
        "torch": torch.__version__,
        "outputs_sha256": {
            f: _sha256(args.out / f)
            for f in (
                "predicted_change.npy",
                "per_token_sd.npy",
                "per_set_sd.npy",
                "unanchored_change.npy",
                "control_unanchored_change.npy",
            )
        },
    }
    (args.out / "record.json").write_text(json.dumps(record, indent=1))
    print(json.dumps({k: v for k, v in record.items() if k not in ("supported", "unsupported")}))


if __name__ == "__main__":
    main()
