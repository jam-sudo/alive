"""Leakage-safe fit-role AnnData artifact library (COMPOSE sub-project A1).

Extractor (metadata before X), deterministic .h5ad generator, re-validating
loader with path safety, and canonical content-identity hashing. See
docs/superpowers/specs/2026-07-02-compose-fit-data-contract-design.md
§2.1/§3/§3.2/§4/§5.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
from scipy import sparse

from alive.provenance import sha256_json

_ALLOWED_ROLES: frozenset[str] = frozenset({"control", "singles", "combo_calibration"})
_CSR_DTYPE = np.float64


class FitRoleArtifactError(ValueError):
    """Raised on any fit-role artifact identity/leakage/validation failure."""


def _check_gene_ids(var_names: Sequence[str]) -> list[str]:
    genes = [str(v) for v in var_names]
    if not genes:
        raise FitRoleArtifactError("var_names must be non-empty")
    if any(g == "" for g in genes):
        raise FitRoleArtifactError("var_names must not contain empty IDs")
    if len(set(genes)) != len(genes):
        raise FitRoleArtifactError("var_names must be unique")
    return genes


def canonical_gene_order_sha256(var_names: Sequence[str]) -> str:
    """SHA-256 (hex) of the canonical, ordered gene-ID list (spec §3.2)."""
    return sha256_json(_check_gene_ids(var_names))


def row_identity_sha256(rows: Sequence[tuple[str, str, str]]) -> str:
    """SHA-256 (hex) of ``[[source_row_id, role, canonical_perturbation], ...]``
    in artifact row order (spec §3.2)."""
    return sha256_json([[str(a), str(b), str(c)] for a, b, c in rows])


def _canonical_csr_digests(X: sparse.csr_matrix) -> dict[str, str]:
    """Canonicalize a CSR matrix (sort indices, drop explicit zeros/dups, fixed
    dtype) and return byte digests of its structure arrays (spec §3.2)."""
    m = sparse.csr_matrix(X, dtype=_CSR_DTYPE, copy=True)
    m.sum_duplicates()
    m.eliminate_zeros()
    m.sort_indices()
    return {
        "shape": list(m.shape),
        "indptr": sha256_json(m.indptr.astype(np.int64).tolist()),
        "indices": sha256_json(m.indices.astype(np.int64).tolist()),
        "data": sha256_json(m.data.astype(_CSR_DTYPE).tolist()),
    }


def content_manifest_sha256(
    *,
    schema_version: int,
    X: sparse.csr_matrix,
    var_names: Sequence[str],
    rows: Sequence[tuple[str, str, str]],
    provenance: Mapping[str, str],
    role_counts: Mapping[str, int],
) -> str:
    """Canonical logical-content identity of a fit-role artifact (spec §3.2).

    Excludes HDF5 metadata / chunk layout / path; invariant to CSR storage
    layout via canonicalization. Includes schema version, CSR structure digests,
    and the gene / row / provenance digests + role counts.
    """
    manifest = {
        "schema_version": int(schema_version),
        "csr": _canonical_csr_digests(X),
        "gene_order_sha256": canonical_gene_order_sha256(var_names),
        "row_identity_sha256": row_identity_sha256(rows),
        "provenance": {str(k): str(v) for k, v in sorted(provenance.items())},
        "role_counts": {str(k): int(v) for k, v in sorted(role_counts.items())},
    }
    return sha256_json(manifest)
