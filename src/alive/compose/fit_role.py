"""Leakage-safe fit-role AnnData artifact library (COMPOSE sub-project A1).

Extractor (metadata before X), deterministic .h5ad generator, re-validating
loader with path safety, and canonical content-identity hashing. See
docs/superpowers/specs/2026-07-02-compose-fit-data-contract-design.md
§2.1/§3/§3.2/§4/§5.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

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


def _canonical_pair(perturbation: str) -> tuple[str, str]:
    """Return the UTF-8 byte-ordered gene pair from a ``GENEA_GENEB`` token."""
    a, b = perturbation.split("_", 1)
    return (a, b) if a.encode("utf-8") < b.encode("utf-8") else (b, a)


@dataclass(frozen=True)
class FitRoleExtraction:
    """Allowed-row-only extraction: the input to the artifact generator.

    Attributes
    ----------
    X : scipy.sparse.csr_matrix
        Raw-count expression for the selected (non-sealed) rows only.
    var_names : tuple of str
        Canonical gene-ID order.
    rows : tuple of tuple of str
        ``(source_row_id, role, canonical_perturbation)`` per selected row, in
        artifact row order.
    role_counts : dict of str to int
        Count of selected rows per allowed role.
    raw_data_sha256 : str
        Exact raw-data digest carried from the committed split manifest.
    pair_manifest_sha256 : str
        Verified committed split-manifest checksum.
    eligibility_hash : str
        Outcome-independent eligibility hash from the split manifest.
    """

    X: sparse.csr_matrix
    var_names: tuple[str, ...]
    rows: tuple[tuple[str, str, str], ...]
    role_counts: dict[str, int]
    raw_data_sha256: str
    pair_manifest_sha256: str
    eligibility_hash: str


class ComposeFitRoleExtractor:
    """Select fit roles from obs metadata and read ONLY the allowed rows.

    ``select_row_ids`` inspects role/perturbation metadata and asserts
    sealed-disjointness + label consistency BEFORE any expression is read;
    ``extract`` then reads only the selected rows via ``row_reader`` (backed
    slicing in production). Sealed expression is never materialized (spec §4).

    A ``singles`` row whose gene participates in a sealed pair is a sealed
    double-unseen single: it is dropped from the selection and never read, so
    its expression cannot leak into the fit (spec §4 step 2, §5). A sealed pair
    appearing under the ``combo_calibration`` role is a mislabel/leakage attempt
    and fails closed.
    """

    def __init__(
        self,
        *,
        obs_role: Sequence[str],
        obs_source_row_id: Sequence[str],
        obs_perturbation: Sequence[str],
        var_names: Sequence[str],
        calibration_pair_ids: Sequence[tuple[str, str]],
        sealed_pair_ids: Sequence[tuple[str, str]],
        raw_data_sha256: str,
        pair_manifest_sha256: str,
        eligibility_hash: str,
        row_reader: Callable[[list[int]], sparse.csr_matrix],
    ) -> None:
        n = len(obs_role)
        if not (len(obs_source_row_id) == len(obs_perturbation) == n):
            raise FitRoleArtifactError("obs columns must be equal length")
        self._role = [str(r) for r in obs_role]
        self._src = [str(s) for s in obs_source_row_id]
        self._pert = [str(p) for p in obs_perturbation]
        self._var_names = _check_gene_ids(var_names)
        self._calib = {tuple(p) for p in calibration_pair_ids}
        self._sealed = {tuple(p) for p in sealed_pair_ids}
        self._sealed_genes = {g for pair in self._sealed for g in pair}
        self._raw_data_sha256 = str(raw_data_sha256)
        self._pair_manifest_sha256 = str(pair_manifest_sha256)
        self._eligibility_hash = str(eligibility_hash)
        self._row_reader = row_reader
        if len(set(self._src)) != n:
            raise FitRoleArtifactError("source_row_id must be unique")

    def select_row_ids(self) -> list[int]:
        """Return the row indices of the allowed fit roles, sealed rows excluded.

        Uses ``obs`` metadata only; never calls ``row_reader``. Fails closed on
        any non-whitelisted role or inconsistent role/perturbation label, and
        drops every sealed double-unseen single so its expression is never read
        (spec §4/§5).

        Returns
        -------
        list of int
            Indices (in original ``obs`` order) of the selected control /
            single / combo-calibration rows.

        Raises
        ------
        FitRoleArtifactError
            On a non-whitelisted role, a sealed pair under a calibration role,
            a combo pair absent from the calibration set, or a label that does
            not match its declared role.
        """
        selected: list[int] = []
        for i, role in enumerate(self._role):
            if role not in _ALLOWED_ROLES:
                raise FitRoleArtifactError(f"row {i}: non-whitelisted role {role!r}")
            pert = self._pert[i]
            if role == "combo_calibration":
                pair = _canonical_pair(pert)
                if pair in self._sealed:
                    raise FitRoleArtifactError(f"row {i}: sealed pair {pair!r} in calibration role")
                if pair not in self._calib:
                    raise FitRoleArtifactError(
                        f"row {i}: pair {pair!r} not a registered calibration pair"
                    )
            elif role == "singles":
                if "_" in pert or pert == "control":
                    raise FitRoleArtifactError(
                        f"row {i}: singles label {pert!r} is not a single gene"
                    )
                if pert in self._sealed_genes:
                    # Sealed double-unseen single: never selected, never read, so
                    # its expression cannot leak into the fit (spec §4/§5).
                    continue
            elif role == "control" and pert != "control":
                raise FitRoleArtifactError(f"row {i}: control label {pert!r} is not 'control'")
            selected.append(i)
        return selected

    def extract(self) -> FitRoleExtraction:
        """Read only the selected rows and assemble the extraction.

        ``select_row_ids`` runs first, so ``row_reader`` is only ever handed
        non-sealed indices.

        Returns
        -------
        FitRoleExtraction
            The allowed-row-only expression plus canonical row/gene identity.

        Raises
        ------
        FitRoleArtifactError
            If selection fails or ``row_reader`` returns the wrong row count.
        """
        idx = self.select_row_ids()
        X = sparse.csr_matrix(self._row_reader(idx))
        if X.shape[0] != len(idx):
            raise FitRoleArtifactError("row_reader returned the wrong number of rows")
        rows = tuple((self._src[i], self._role[i], self._pert[i]) for i in idx)
        counts = {r: sum(1 for _, rr, _ in rows if rr == r) for r in sorted(_ALLOWED_ROLES)}
        return FitRoleExtraction(
            X=X,
            var_names=tuple(self._var_names),
            rows=rows,
            role_counts=counts,
            raw_data_sha256=self._raw_data_sha256,
            pair_manifest_sha256=self._pair_manifest_sha256,
            eligibility_hash=self._eligibility_hash,
        )


def extract_fit_roles(*, extractor: ComposeFitRoleExtractor) -> FitRoleExtraction:
    """Public entry point: run the audited extractor once.

    Parameters
    ----------
    extractor : ComposeFitRoleExtractor
        A configured extractor whose metadata has already been supplied.

    Returns
    -------
    FitRoleExtraction
        The allowed-row-only extraction (sealed rows never materialized).
    """
    return extractor.extract()
