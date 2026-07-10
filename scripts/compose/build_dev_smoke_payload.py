#!/usr/bin/env python
"""DEV-POD-SMOKE-ONLY payload builder for the real GEARS/CPA worker smokes.

Assembles a valid, leakage-safe fit-role ``.h5ad`` + a schema-v2 worker payload
from a real (or synthetic) AnnData, so a dev pod can drive
``scripts/baselines/{gears,cpa}_worker.py`` end-to-end and observe an outcome-free
Norman fit-role smoke (plan Task 1.2/1.3 Step 2).

**This is NOT the production PREPARE carrier** (sub-project C, still
``UnsupportedModeError``). It opens NO seal, reads NO sealed outcome, and makes NO
scientific claim: the sealed/calibration combo split is chosen purely by canonical
pair-ID sort under a fixed seed — an OUTCOME-FREE dev selection, never by response
strength. Sealed combo cells are excluded from the artifact (never materialised);
they enter the workers only as ``sealed_pair_ids`` for the leakage guard.

The heavy per-cell reductions (``singles_response``, ``calibration_delta``) are
computed with the exact frozen §2.3 response operator so the payload the worker
receives is contract-valid (``baseline_subprocess._validate_payload``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
from dataclasses import dataclass
from typing import Protocol, Sequence

import numpy as np
from scipy import sparse

from alive.compose.baseline_subprocess import write_payload
from alive.compose.fit_role import (
    ComposeFitRoleExtractor,
    apply_response_projection,
    build_response_projection,
    extract_fit_roles,
    generate_fit_role_artifact,
)
from alive.compose.response import fit_response_space

_DEV_SENTINEL_PREFIX = "dev-smoke"


class _HashLike(Protocol):
    """Minimal structural type implemented by ``hashlib`` hash objects."""

    def update(self, data: bytes, /) -> None: ...


def _canonical_pair(a: str, b: str) -> tuple[str, str]:
    """Return the UTF-8 byte-ordered ``(gene_a, gene_b)`` pair."""
    return (a, b) if a.encode("utf-8") < b.encode("utf-8") else (b, a)


def _dev_sentinel(*parts: str) -> str:
    """Deterministic non-empty provenance sentinel for dev-smoke artifacts."""
    h = hashlib.sha256(("\0".join(parts)).encode("utf-8")).hexdigest()
    return f"{_DEV_SENTINEL_PREFIX}:{h[:32]}"


@dataclass(frozen=True)
class PerturbationUniverse:
    """The control / singles / combo tokens parsed from an obs perturbation column."""

    control_token: str
    single_genes: tuple[str, ...]
    combo_pairs: tuple[tuple[str, str], ...]
    token_of_pair: dict[tuple[str, str], str]


def parse_perturbation_universe(
    obs_perturbation: list[str],
    *,
    control_token: str,
    combo_sep: str,
) -> PerturbationUniverse:
    """Parse control / single / combo tokens from an obs perturbation column.

    Combo tokens are ``GENEA<sep>GENEB``; a combo is retained only when BOTH of
    its genes also occur as single-gene perturbations, so every combo is
    composable from learned single signatures (the unseen-combo generalisation
    both backends rely on). Selection here is metadata-only and outcome-free.

    Parameters
    ----------
    obs_perturbation : list of str
        The raw obs perturbation tokens.
    control_token : str
        The token denoting a control cell.
    combo_sep : str
        Separator between the two single-gene tokens of a combo.

    Returns
    -------
    PerturbationUniverse
        Parsed control token, sorted unique single genes, sorted canonical combo
        pairs (both genes are singles), and each pair's raw obs token.
    """
    singles: set[str] = set()
    combo_tokens: dict[tuple[str, str], str] = {}
    for tok in obs_perturbation:
        if tok == control_token:
            continue
        if combo_sep in tok:
            a, b = tok.split(combo_sep, 1)
            pair = _canonical_pair(a, b)
            # Fail closed on a combo present under more than one raw spelling (e.g.
            # 'CEBPE_KLF1' and 'KLF1_CEBPE'). The in-scope row filter keys on the raw
            # token, so a second spelling would silently under-sample that pair and
            # make its calibration delta obs-row-order dependent. The harness requires
            # a single canonical spelling per combo (Norman GI data satisfies this).
            if pair in combo_tokens and combo_tokens[pair] != tok:
                raise ValueError(
                    f"combo pair {pair} appears under multiple raw spellings "
                    f"{combo_tokens[pair]!r} and {tok!r}; the dev-smoke harness requires "
                    "a single canonical spelling per combo"
                )
            combo_tokens[pair] = tok
        else:
            singles.add(tok)
    combos = tuple(
        sorted(pair for pair in combo_tokens if pair[0] in singles and pair[1] in singles)
    )
    return PerturbationUniverse(
        control_token=control_token,
        single_genes=tuple(sorted(singles)),
        combo_pairs=combos,
        token_of_pair={pair: combo_tokens[pair] for pair in combos},
    )


def select_outcome_free_split(
    universe: PerturbationUniverse,
    *,
    n_sealed: int,
    n_calibration: int,
    seed: int,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Choose disjoint sealed + calibration combo rosters WITHOUT any outcome.

    The eligible combos are canonically sorted, then deterministically shuffled by
    a fixed-seed permutation over the sorted list; the first ``n_sealed`` become
    the sealed request roster and the next ``n_calibration`` the calibration
    roster. No expression / response value is ever consulted — this is a dev
    selection, not a registered scientific split.

    Parameters
    ----------
    universe : PerturbationUniverse
        The parsed perturbation universe.
    n_sealed : int
        Number of sealed (requested, held-out) combo pairs.
    n_calibration : int
        Number of calibration (fit) combo pairs.
    seed : int
        Fixed seed for the deterministic ID-order permutation.

    Returns
    -------
    tuple
        ``(sealed_pairs, calibration_pairs)`` — disjoint canonical pair lists.

    Raises
    ------
    ValueError
        If there are too few eligible combos for the requested rosters.
    """
    combos = list(universe.combo_pairs)
    if len(combos) < n_sealed + n_calibration:
        raise ValueError(f"need >= {n_sealed + n_calibration} eligible combos, have {len(combos)}")
    order = np.random.default_rng(seed).permutation(len(combos))
    picked = [combos[i] for i in order[: n_sealed + n_calibration]]
    sealed = sorted(picked[:n_sealed])
    calibration = sorted(picked[n_sealed : n_sealed + n_calibration])
    return sealed, calibration


def _raw_counts_csr(adata, row_indices: Sequence[int]) -> sparse.csr_matrix:
    """Read selected rows only and return their raw-count CSR matrix.

    Fit-role artifacts require finite, non-negative, integer-valued counts. Prefer
    an explicit ``counts`` layer; otherwise use ``X``.  The source is sliced
    *before* CSR conversion so rows assigned to the dev-sealed roster are never
    read or materialised by this builder.
    """
    src = adata.layers["counts"] if "counts" in adata.layers else adata.X
    idx = np.asarray(row_indices, dtype=np.int64)
    m = sparse.csr_matrix(src[idx], dtype=np.float64)
    m.eliminate_zeros()
    m.sort_indices()
    if m.data.size and (
        not np.all(np.isfinite(m.data)) or np.any(m.data < 0) or np.any(m.data != np.floor(m.data))
    ):
        raise ValueError(
            "expression matrix must contain finite, non-negative, integer-valued raw counts; "
            "supply raw counts in layers['counts'] or X"
        )
    return m


def _update_length_prefixed(h: _HashLike, label: bytes, value: bytes) -> None:
    """Add one unambiguous labelled byte string to ``h``."""
    h.update(struct.pack(">Q", len(label)))
    h.update(label)
    h.update(struct.pack(">Q", len(value)))
    h.update(value)


def _update_text_sequence(h: _HashLike, label: bytes, values: Sequence[str]) -> None:
    """Add an ordered UTF-8 text sequence to ``h`` with length framing."""
    h.update(struct.pack(">Q", len(label)))
    h.update(label)
    h.update(struct.pack(">Q", len(values)))
    for value in values:
        encoded = str(value).encode("utf-8")
        h.update(struct.pack(">Q", len(encoded)))
        h.update(encoded)


def _allowed_source_sha256(
    *,
    X: sparse.csr_matrix,
    source_row_ids: Sequence[str],
    perturbations: Sequence[str],
    gene_order: Sequence[str],
) -> str:
    """Return a path-independent digest of the rows this dev payload may read.

    The digest covers canonical CSR counts plus ordered source-row IDs,
    perturbation tokens, and gene IDs.  It intentionally excludes dev-sealed rows:
    their expression is neither read nor part of the fit/payload source identity.
    Equivalent allowed content therefore has the same identity at any output path,
    while any allowed-row/count/row-ID/gene mutation changes it.
    """
    matrix = sparse.csr_matrix(X, dtype=np.float64, copy=True)
    matrix.eliminate_zeros()
    matrix.sort_indices()
    if matrix.shape != (len(source_row_ids), len(gene_order)):
        raise ValueError("allowed source matrix is not aligned to row/gene identity")
    if len(perturbations) != len(source_row_ids):
        raise ValueError("allowed perturbation roster is not aligned to source rows")

    h = hashlib.sha256()
    _update_length_prefixed(h, b"schema", b"compose_dev_smoke_allowed_source_v1")
    _update_length_prefixed(
        h,
        b"shape",
        np.asarray(matrix.shape, dtype=">u8").tobytes(order="C"),
    )
    _update_text_sequence(h, b"source_row_ids", source_row_ids)
    _update_text_sequence(h, b"perturbations", perturbations)
    _update_text_sequence(h, b"gene_order", gene_order)
    _update_length_prefixed(
        h,
        b"csr_indptr",
        np.asarray(matrix.indptr, dtype=">u8").tobytes(order="C"),
    )
    _update_length_prefixed(
        h,
        b"csr_indices",
        np.asarray(matrix.indices, dtype=">u8").tobytes(order="C"),
    )
    _update_length_prefixed(
        h,
        b"csr_counts",
        np.asarray(matrix.data, dtype=">u8").tobytes(order="C"),
    )
    return "sha256:" + h.hexdigest()


def build_dev_smoke_payload(
    adata,
    *,
    out_dir: str,
    artifact_path: str,
    control_token: str,
    combo_sep: str,
    n_hvg: int,
    pca_dim: int,
    seed: int,
    n_sealed: int,
    n_calibration: int,
) -> dict:
    """Build a fit-role artifact + a contract-valid worker payload from ``adata``.

    Parameters
    ----------
    adata : anndata.AnnData
        Source data with an ``obs['perturbation']`` column and raw counts in
        ``X`` or ``layers['counts']``.
    out_dir : str
        Work directory the ``payload.json`` is written into.
    artifact_path : str
        Destination ``.h5ad`` path for the immutable fit-role artifact (under an
        approved artifacts root; must not already exist).
    control_token, combo_sep : str
        Perturbation-token conventions (config ``data.control_token`` /
        ``data.combo_sep``).
    n_hvg, pca_dim, seed : int
        Response-space fit parameters (config ``response.n_hvg`` / ``pca_dim`` /
        ``data.seed``).
    n_sealed, n_calibration : int
        Sizes of the outcome-free sealed + calibration combo rosters.

    Returns
    -------
    dict
        A ``compose_dev_smoke_manifest_v1`` describing the produced artifact,
        payload, approved root, and the sealed/calibration rosters with their
        recomputed zero-overlap proof.
    """
    perts_all = [str(p) for p in adata.obs["perturbation"]]
    universe = parse_perturbation_universe(
        perts_all, control_token=control_token, combo_sep=combo_sep
    )
    sealed, calibration = select_outcome_free_split(
        universe, n_sealed=n_sealed, n_calibration=n_calibration, seed=seed
    )

    # Build the expression matrix from ALLOWED rows directly: control + singles +
    # calibration combos.  Dev-sealed combo IDs participate in the metadata-only
    # split/guard, but their expression rows are never handed to ``adata.X`` /
    # ``layers['counts']`` and never occupy an intermediate matrix.
    allowed_tokens = (
        {control_token}
        | set(universe.single_genes)
        | {universe.token_of_pair[p] for p in calibration}
    )
    allowed_source_idx = [i for i, tok in enumerate(perts_all) if tok in allowed_tokens]
    perts = [perts_all[i] for i in allowed_source_idx]
    obs_names = np.asarray(adata.obs_names)
    source_ids = [str(obs_names[i]) for i in allowed_source_idx]
    var_names = [str(v) for v in adata.var_names]
    X_raw = _raw_counts_csr(adata, allowed_source_idx)
    raw_data_sha256 = _allowed_source_sha256(
        X=X_raw,
        source_row_ids=source_ids,
        perturbations=perts,
        gene_order=var_names,
    )

    # 1. fit-role artifact: control + singles + calibration combos (sealed excluded).
    extractor = ComposeFitRoleExtractor(
        obs_source_row_id=source_ids,
        obs_perturbation=perts,
        var_names=var_names,
        calibration_pair_ids=calibration,
        sealed_pair_ids=sealed,
        control_token=control_token,
        raw_data_sha256=raw_data_sha256,
        pair_manifest_sha256=_dev_sentinel("pairs", *[f"{a}_{b}" for a, b in sealed + calibration]),
        eligibility_hash=_dev_sentinel("elig", *universe.single_genes),
        row_reader=lambda idx: X_raw[idx],
        combo_sep=combo_sep,
    )
    extraction = extract_fit_roles(extractor=extractor)
    os.makedirs(os.path.dirname(os.path.abspath(artifact_path)), exist_ok=True)
    spec = generate_fit_role_artifact(
        extraction=extraction,
        out_path=artifact_path,
        config_sha256=_dev_sentinel("cfg"),
        data_card_sha256=_dev_sentinel("dc"),
        calibration_gene_set_hash=_dev_sentinel("cg"),
        generator_code_sha256=_dev_sentinel("gen"),
        writer_environment_sha256=_dev_sentinel("env"),
    )

    # 2. response space on control + eligible singles from the FULL source matrix.
    role_of_row = [universe_role(p, universe, combo_sep, sealed, calibration) for p in perts]
    control_idx = np.array([i for i, r in enumerate(role_of_row) if r == "control"], dtype=np.int64)
    single_idx = np.array([i for i, r in enumerate(role_of_row) if r == "singles"], dtype=np.int64)
    space = fit_response_space(
        X_raw,
        control_idx=control_idx,
        eligible_single_idx=single_idx,
        n_hvg=n_hvg,
        pca_dim=pca_dim,
        seed=seed,
    )
    control_mean = space.project(X_raw, control_idx).mean(axis=0)
    projection = build_response_projection(
        space,
        gene_order=var_names,
        control_mean=control_mean,
        raw_data_sha256=raw_data_sha256,
    )

    # 3. per-role response reductions (frozen §2.3 operator), all outcome-free roles.
    single_gene_ids = list(universe.single_genes)
    pert_to_rows: dict[str, list[int]] = {}
    for i, tok in enumerate(perts):
        pert_to_rows.setdefault(tok, []).append(i)

    def _delta(tok: str) -> np.ndarray:
        rows = np.array(pert_to_rows[tok], dtype=np.int64)
        z = apply_response_projection(
            projection,
            np.asarray(X_raw[rows].todense(), dtype=np.float64),
            var_names,
            representation="cell_raw_counts",
        )
        return z.mean(axis=0) - np.asarray(projection["control_mean"], dtype=np.float64)

    singles_response = np.stack([_delta(g) for g in single_gene_ids]).astype(np.float64)
    calibration_delta = np.stack(
        [_delta(universe.token_of_pair[pair]) for pair in calibration]
    ).astype(np.float64)
    oof_folds = [
        int.from_bytes(hashlib.sha256(f"{a}\0{b}".encode()).digest()[:2], "big") % 5
        for a, b in calibration
    ]

    payload = {
        "schema_version": 2,
        "response_dim": pca_dim,
        "seed": seed,
        "allowed_roles": ["combo_calibration", "singles"],
        "pair_ids": [list(p) for p in sealed],
        "single_gene_ids": single_gene_ids,
        "singles_response": singles_response.tolist(),
        "control_mean": projection["control_mean"],
        "calibration_pair_ids": [list(p) for p in calibration],
        "calibration_delta": calibration_delta.tolist(),
        "pca_components": projection["pca_components"],
        "oof_folds": oof_folds,
        "fit_role_artifact": spec.to_payload_block(),
        "response_projection": projection,
    }
    payload_sha256 = write_payload(out_dir, payload)

    approved_root = os.path.realpath(os.path.dirname(os.path.abspath(artifact_path)))
    sealed_sorted = sorted(sealed)
    calib_sorted = sorted(calibration)
    overlap = sorted(set(sealed_sorted) & set(calib_sorted))
    return {
        "schema": "compose_dev_smoke_manifest_v1",
        "note": "DEV-POD-SMOKE-ONLY. Opens no seal; outcome-free ID-sorted split.",
        "approved_root": approved_root,
        "work_dir": os.path.realpath(out_dir),
        "payload_sha256": payload_sha256,
        "raw_data_sha256": raw_data_sha256,
        "artifact_path": os.path.realpath(artifact_path),
        "artifact_sha256": spec.sha256,
        "artifact_content_manifest_sha256": spec.content_manifest_sha256,
        "role_counts": dict(spec.role_counts),
        "n_single_gene_ids": len(single_gene_ids),
        "training_pair_roster": [list(p) for p in calib_sorted],
        "sealed_pair_roster": [list(p) for p in sealed_sorted],
        "sealed_pair_overlap_count": len(overlap),
        "response_dim": pca_dim,
        "n_hvg": n_hvg,
    }


def universe_role(
    tok: str,
    universe: PerturbationUniverse,
    combo_sep: str,
    sealed: list[tuple[str, str]],
    calibration: list[tuple[str, str]],
) -> str | None:
    """Classify an obs token into control / singles / combo_calibration / None.

    ``None`` marks a sealed combo (excluded, never read). Mirrors
    ``ComposeFitRoleExtractor._role_of`` for the response-space index derivation.
    """
    if tok == universe.control_token:
        return "control"
    if combo_sep in tok:
        a, b = tok.split(combo_sep, 1)
        pair = _canonical_pair(a, b)
        if pair in set(sealed):
            return None
        if pair in set(calibration):
            return "combo_calibration"
        return None  # a combo neither sealed nor calibration is out of scope here
    return "singles"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DEV-POD-SMOKE-ONLY worker payload builder")
    ap.add_argument("--h5ad", required=True, help="source AnnData with obs['perturbation']")
    ap.add_argument("--work-dir", required=True, help="output dir for payload.json")
    ap.add_argument("--artifact", required=True, help="output fit-role .h5ad path (approved root)")
    ap.add_argument("--manifest-out", required=True, help="output dev-smoke manifest json path")
    ap.add_argument("--control-token", default="control")
    ap.add_argument("--combo-sep", default="_")
    ap.add_argument("--n-hvg", type=int, default=1500)
    ap.add_argument("--pca-dim", type=int, default=50)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--n-sealed", type=int, default=4)
    ap.add_argument("--n-calibration", type=int, default=8)
    a = ap.parse_args(argv)

    import anndata as ad

    # Backed mode keeps the source expression matrix on disk until the builder has
    # selected its metadata-only allowed row indices.  ``_raw_counts_csr`` then
    # reads only those rows; dev-sealed expression is never eagerly materialised.
    adata = ad.read_h5ad(a.h5ad, backed="r")
    try:
        manifest = build_dev_smoke_payload(
            adata,
            out_dir=a.work_dir,
            artifact_path=a.artifact,
            control_token=a.control_token,
            combo_sep=a.combo_sep,
            n_hvg=a.n_hvg,
            pca_dim=a.pca_dim,
            seed=a.seed,
            n_sealed=a.n_sealed,
            n_calibration=a.n_calibration,
        )
    finally:
        adata.file.close()
    with open(a.manifest_out, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
