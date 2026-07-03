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


def _canonical_pair(perturbation: str, combo_sep: str = "_") -> tuple[str, str]:
    """Return the UTF-8 byte-ordered gene pair from a ``GENEA<sep>GENEB`` token.

    Parameters
    ----------
    perturbation : str
        A combo perturbation token containing exactly one ``combo_sep``.
    combo_sep : str, default ``"_"``
        Separator between the two single-gene tokens.

    Returns
    -------
    tuple of str
        ``(gene_a, gene_b)`` ordered by UTF-8 byte comparison so the pair is
        canonical regardless of the order the genes appear in the token.
    """
    a, b = perturbation.split(combo_sep, 1)
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
    """Derive fit roles from obs perturbation metadata and read ONLY allowed rows.

    ``select_row_ids`` derives each row's role from its perturbation token + the
    calibration/sealed pair sets (spec §7.1) BEFORE any expression is read;
    ``extract`` then reads only the selected rows via ``row_reader`` (backed
    slicing in production). Sealed COMBO cells are excluded and never read, so
    sealed expression is never materialized (spec §4). Singles are ALWAYS
    retained — a double/single-unseen pair still needs its single signatures
    ``z_g``, ``z_h``, and singles are never sealed.
    """

    def __init__(
        self,
        *,
        obs_source_row_id: Sequence[str],
        obs_perturbation: Sequence[str],
        var_names: Sequence[str],
        calibration_pair_ids: Sequence[tuple[str, str]],
        sealed_pair_ids: Sequence[tuple[str, str]],
        control_token: str,
        raw_data_sha256: str,
        pair_manifest_sha256: str,
        eligibility_hash: str,
        row_reader: Callable[[list[int]], sparse.csr_matrix],
        combo_sep: str = "_",
    ) -> None:
        n = len(obs_perturbation)
        if len(obs_source_row_id) != n:
            raise FitRoleArtifactError("obs columns must be equal length")
        self._src = [str(s) for s in obs_source_row_id]
        self._pert = [str(p) for p in obs_perturbation]
        self._var_names = _check_gene_ids(var_names)
        self._calib = {tuple(p) for p in calibration_pair_ids}
        self._sealed = {tuple(p) for p in sealed_pair_ids}
        self._control_token = str(control_token)
        self._combo_sep = str(combo_sep)
        self._raw_data_sha256 = str(raw_data_sha256)
        self._pair_manifest_sha256 = str(pair_manifest_sha256)
        self._eligibility_hash = str(eligibility_hash)
        self._row_reader = row_reader
        if len(set(self._src)) != n:
            raise FitRoleArtifactError("source_row_id must be unique")

    def _role_of(self, pert: str) -> str | None:
        """Derive a perturbation token's fit role.

        Parameters
        ----------
        pert : str
            A single obs perturbation token.

        Returns
        -------
        str or None
            The allowed fit role (``control`` / ``singles`` / ``combo_calibration``),
            or ``None`` when the row is a sealed combo cell to exclude (never read).

        Raises
        ------
        FitRoleArtifactError
            When a combo pair is in both the calibration and sealed sets, or in
            neither (unregistered/ambiguous) — fail closed.
        """
        if pert == self._control_token:
            return "control"
        if self._combo_sep in pert:
            pair = _canonical_pair(pert, self._combo_sep)
            in_calib = pair in self._calib
            in_sealed = pair in self._sealed
            if in_calib and in_sealed:
                raise FitRoleArtifactError(
                    f"combo pair {pair!r} is in both calibration and sealed sets"
                )
            if in_sealed:
                return None  # sealed combo cell: excluded, never read
            if in_calib:
                return "combo_calibration"
            raise FitRoleArtifactError(
                f"combo pair {pair!r} is neither a calibration nor a sealed pair"
            )
        return "singles"  # single-gene perturbation is always a retained fit role

    def select_row_ids(self) -> list[int]:
        """Return the row indices of the derived fit roles, sealed combos excluded.

        Uses ``obs`` metadata only; never calls ``row_reader`` (spec §4/§5).

        Returns
        -------
        list of int
            Indices (in original ``obs`` order) of the selected control /
            single / combo-calibration rows.

        Raises
        ------
        FitRoleArtifactError
            On a combo pair that is unregistered or in both pair sets.
        """
        return [i for i, pert in enumerate(self._pert) if self._role_of(pert) is not None]

    def extract(self) -> FitRoleExtraction:
        """Read only the selected rows and assemble the extraction.

        Roles are derived first, so ``row_reader`` is only ever handed
        non-sealed indices.

        Returns
        -------
        FitRoleExtraction
            The allowed-row-only expression plus canonical row/gene identity.

        Raises
        ------
        FitRoleArtifactError
            If role derivation fails or ``row_reader`` returns the wrong row count.
        """
        roles = [self._role_of(p) for p in self._pert]
        idx = [i for i, role in enumerate(roles) if role is not None]
        X = sparse.csr_matrix(self._row_reader(idx))
        if X.shape[0] != len(idx):
            raise FitRoleArtifactError("row_reader returned the wrong number of rows")
        rows = tuple((self._src[i], roles[i], self._pert[i]) for i in idx)
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
