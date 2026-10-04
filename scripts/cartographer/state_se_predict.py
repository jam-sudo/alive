"""Frozen Arc State ST-SE-Replogle fewshot/k562 final.ckpt adapter (P3; isolated State runtime).

Same contract as ``state_predict.py`` (anchored on non-targeting, uniform 56 batch tokens,
fixed R control sets of 64 ``C_input`` cells with the same seed, so the control cells equal P1's).
Difference: control cells are embedded with the SE-600M ``model.safetensors`` weights (verified
to reproduce training ``X_state``) and predictions are decoded to the 2,000 HVGs by the
checkpoint's ``gene_decoder``. SE sampling is seeded; the seed is part of predictor identity.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
from pathlib import Path

import numpy as np

_BASE = importlib.util.spec_from_file_location(
    "state_predict", Path(__file__).parent / "state_predict.py"
)
sp = importlib.util.module_from_spec(_BASE)
_BASE.loader.exec_module(sp)


def se_input(counts: np.ndarray, columns: list[int]) -> np.ndarray:
    """SE input matching the verified concat recipe: log1p(CP10k over the full axis) on SE genes."""
    depth = counts.sum(1, keepdims=True)
    if np.any(depth <= 0):
        raise ValueError("zero-depth cell in control input")
    return np.log1p(1e4 * counts / depth)[:, columns].astype(np.float32)


def main() -> None:  # pragma: no cover - isolated runtime entry point
    import anndata as ad
    import torch
    from omegaconf import OmegaConf
    from safetensors.torch import load_file
    from state.emb.inference import Inference
    from state.emb.nn.model import StateEmbeddingModel
    from state.tx.models.state_transition import StateTransitionPerturbationModel

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text())
    for key, digest in spec["sha256"].items():
        if sp._sha256(Path(spec["paths"][key])) != digest:
            raise ValueError(f"input hash mismatch: {key}")

    rows = np.load(spec["paths"]["control_rows"])
    manifest = json.loads(Path(spec["paths"]["role_manifest"]).read_text())
    input_rows = np.array(sorted(manifest["roles"]["C_input"]))
    sp.require_input_role(input_rows, manifest)
    sets = sp.control_sets(len(input_rows), spec["n_sets"], sp.SET_SIZE, spec["seed"])
    position = {int(r): i for i, r in enumerate(rows.tolist())}
    X = np.load(spec["paths"]["control_matrix"], mmap_mode="r")
    chosen = input_rows[sets.ravel()]
    counts = np.asarray(X[[position[int(r)] for r in chosen]], dtype=np.float64)
    adata = ad.AnnData(X=se_input(counts, spec["se_columns"]))
    adata.var_names = spec["se_gene_names"]

    se_dir = Path(spec["paths"]["se_weights"]).parent
    cfg = OmegaConf.load(se_dir / "config.yaml")
    m = cfg.model
    se = StateEmbeddingModel(
        token_dim=5120,
        d_model=m.emsize,
        nhead=m.nhead,
        d_hid=m.d_hid,
        nlayers=m.nlayers,
        output_dim=m.output_dim,
        dropout=0.0,
        cfg=cfg,
    )
    missing, unexpected = se.load_state_dict(load_file(spec["paths"]["se_weights"]), strict=False)
    if [k for k in missing if not k.startswith(("pe_embedding", "gene_embedding_layer"))] or [
        k for k in unexpected if k != "pe_embedding.weight"
    ]:
        raise ValueError("SE state_dict mismatch")
    pe = torch.load(se_dir / "protein_embeddings.pt", map_location="cpu", weights_only=False)
    se.pe_embedding = torch.nn.Embedding.from_pretrained(torch.vstack(list(pe.values())))
    se.eval()
    inf = Inference(cfg=cfg, protein_embeds=pe)
    inf.model = se
    torch.manual_seed(spec["se_seed"])
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "controls.h5ad"
        adata.write_h5ad(path)
        emb = inf.encode_adata(str(path), emb_key="X_state")
    ctrl = emb.reshape(spec["n_sets"], sp.SET_SIZE, -1).astype(np.float32)
    # Baseline for the unanchored diagnostic: the same cells on the HVG model scale (as P1).
    ctrl_genes = sp.model_scale(counts, spec["hvg_columns"]).reshape(
        spec["n_sets"], sp.SET_SIZE, -1
    )

    ck = torch.load(spec["paths"]["checkpoint"], map_location="cpu", weights_only=True)
    model = StateTransitionPerturbationModel(**ck["hyper_parameters"])
    model.load_state_dict(ck["state_dict"], strict=True)
    model.eval()
    device = torch.device(spec.get("device", "cpu"))
    model.to(device)
    pert_index = json.loads(Path(spec["paths"]["pert_index"]).read_text())
    supported, unsupported = sp.resolve_queries(spec["queries"], pert_index)
    n_sets, n_cells, dim = ctrl.shape
    ctrl_t = torch.tensor(ctrl, device=device)

    def predict(_ctrl, p, b):
        pert = torch.zeros(n_sets * n_cells, len(pert_index), device=device)
        pert[:, p] = 1.0
        batch = {
            "ctrl_cell_emb": ctrl_t.reshape(-1, dim),
            "pert_emb": pert,
            "batch": torch.full((n_sets * n_cells,), b, dtype=torch.long, device=device),
        }
        with torch.no_grad():
            genes = model.gene_decoder(model(batch, padded=True))
        return genes.reshape(n_sets, n_cells, -1).float().cpu().numpy()

    control_index = pert_index[sp.CONTROL_LABEL]
    base = sp.predicted_change(predict, ctrl_genes, control_index)
    changes = np.zeros((len(supported), base[0].shape[0]), dtype=np.float32)
    token_sd, set_sd = np.zeros_like(changes), np.zeros_like(changes)
    for i, (_, p) in enumerate(supported):
        change, diag = sp.anchored_change(predict, ctrl_genes, p, control_index, base=base)
        changes[i], token_sd[i], set_sd[i] = (
            change,
            diag["per_token_change"].std(0),
            diag["per_set_change"].std(0),
        )
    args.out.mkdir(parents=True, exist_ok=False)
    for name, arr in (
        ("predicted_change.npy", changes),
        ("per_token_sd.npy", token_sd),
        ("per_set_sd.npy", set_sd),
        ("control_embeddings.npy", ctrl),
    ):
        np.save(args.out / name, arr)
    record = {
        "estimand": "anchored decoded genes: gene_decoder(pred(p)) - gene_decoder(pred(NT))",
        "spec_sha256": sp._sha256(args.spec),
        "supported": [n for n, _ in supported],
        "unsupported": unsupported,
        "n_sets": n_sets,
        "set_size": n_cells,
        "n_batch_tokens": sp.N_BATCH_TOKENS,
        "device": str(device),
        "torch": torch.__version__,
        "outputs_sha256": {
            f: sp._sha256(args.out / f)
            for f in (
                "predicted_change.npy",
                "per_token_sd.npy",
                "per_set_sd.npy",
                "control_embeddings.npy",
            )
        },
    }
    (args.out / "record.json").write_text(json.dumps(record, indent=1))
    print(json.dumps({k: v for k, v in record.items() if k not in ("supported", "unsupported")}))


if __name__ == "__main__":
    main()
