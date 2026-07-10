"""Leakage-safe fit-role AnnData artifact library (COMPOSE sub-project A1).

Extractor (metadata before X), deterministic .h5ad generator, re-validating
loader with path safety, and canonical content-identity hashing. See
docs/superpowers/specs/2026-07-02-compose-fit-data-contract-design.md
§2.1/§3/§3.2/§4/§5.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from scipy import sparse

from alive.compose.response import RESPONSE_TRANSFORM, ResponseSpace, verify_response_artifact
from alive.provenance import sha256_json

_ALLOWED_ROLES: frozenset[str] = frozenset({"control", "singles", "combo_calibration"})
_CSR_DTYPE = np.float64
_ARTIFACT_SCHEMA_VERSION = 1


class FitRoleArtifactError(ValueError):
    """Raised on any fit-role artifact identity/leakage/validation failure."""


def _sha256_open_fd(fd: int) -> str:
    """Hash an already-open descriptor without changing its final offset."""
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        chunk = os.read(fd, 1 << 20)
        if not chunk:
            break
        digest.update(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    return digest.hexdigest()


def read_verified_fit_role_artifact(
    path: str,
    *,
    spec: "FitRoleArtifactSpec",
    approved_root: str,
):
    """Read the exact fit-role bytes named by ``spec`` through one stable FD.

    ``validate_fit_role_artifact`` performs the full logical contract audit.  A
    worker must then train on the *same byte identity*, not reopen the pathname
    unchecked after validation.  This loader opens a regular file with
    ``O_NOFOLLOW``, verifies its SHA-256, asks HDF5 to read through the descriptor
    path, and re-hashes the still-open descriptor after the read.  Renaming or
    replacing ``path`` therefore cannot redirect the model to different bytes.

    The returned AnnData is in-memory (never backed), so the descriptor can be
    closed before model fitting without losing the verified snapshot.
    """
    import anndata as ad

    resolved = _assert_canonical_path(path, approved_root)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(resolved, flags)
    except OSError as exc:
        raise FitRoleArtifactError(f"cannot open fit-role artifact safely: {exc}") from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise FitRoleArtifactError("fit-role artifact descriptor is not a regular file")
        before = "sha256:" + _sha256_open_fd(fd)
        if before != spec.sha256:
            raise FitRoleArtifactError("artifact file SHA mismatch on stable descriptor")

        fd_root = "/proc/self/fd" if os.path.isdir("/proc/self/fd") else "/dev/fd"
        try:
            adata = ad.read_h5ad(os.path.join(fd_root, str(fd)))
        except Exception as exc:
            raise FitRoleArtifactError(f"cannot read verified fit-role descriptor: {exc}") from exc

        after = "sha256:" + _sha256_open_fd(fd)
        if after != before:
            raise FitRoleArtifactError("fit-role artifact bytes changed while being read")
        post = os.fstat(fd)
        if (post.st_dev, post.st_ino, post.st_size) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
        ):
            raise FitRoleArtifactError("fit-role artifact identity changed while being read")
        _validate_loaded_snapshot_identity(adata, spec=spec)
        return adata
    finally:
        os.close(fd)


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


def _validate_loaded_snapshot_identity(adata, *, spec: "FitRoleArtifactSpec") -> None:
    """Bind the exact returned in-memory AnnData to the trusted artifact spec.

    Before/after descriptor hashes reject persistent replacement, but a hostile
    writer could mutate an HDF5 node during the read and restore the original file
    before the second hash (an ABA race).  Recomputing the logical identity from
    the returned snapshot proves that the object handed to model fitting is the
    same content that the independently validated spec names.
    """
    try:
        roles = [str(value) for value in adata.obs["role"]]
        if not set(roles) <= _ALLOWED_ROLES:
            raise FitRoleArtifactError("loaded snapshot contains a non-whitelisted role")
        perturbations = [str(value) for value in adata.obs["perturbation"]]
        source_rows = [str(value) for value in adata.obs["source_row_id"]]
        if any(not value for value in source_rows) or len(source_rows) != len(set(source_rows)):
            raise FitRoleArtifactError(
                "loaded snapshot source_row_id values are not unique/non-empty"
            )
        genes = [str(value) for value in adata.var_names]
        rows = tuple(zip(source_rows, roles, perturbations))
        role_counts = {
            role: sum(observed == role for observed in roles) for role in sorted(_ALLOWED_ROLES)
        }
        provenance = {str(key): str(value) for key, value in dict(adata.uns["provenance"]).items()}
        for key in ("raw_data_sha256", "pair_manifest_sha256", "eligibility_hash"):
            if provenance.get(key) != str(getattr(spec, key)):
                raise FitRoleArtifactError(f"loaded snapshot {key} differs from spec")
        if canonical_gene_order_sha256(genes) != spec.gene_order_sha256:
            raise FitRoleArtifactError("loaded snapshot gene-order digest differs from spec")
        if row_identity_sha256(rows) != spec.row_identity_sha256:
            raise FitRoleArtifactError("loaded snapshot row-identity digest differs from spec")
        if provenance.get("gene_order_sha256") != spec.gene_order_sha256:
            raise FitRoleArtifactError(
                "loaded snapshot provenance gene-order digest differs from spec"
            )
        if provenance.get("row_identity_sha256") != spec.row_identity_sha256:
            raise FitRoleArtifactError(
                "loaded snapshot provenance row-identity digest differs from spec"
            )
        recomputed = content_manifest_sha256(
            schema_version=_ARTIFACT_SCHEMA_VERSION,
            X=sparse.csr_matrix(adata.X),
            var_names=genes,
            rows=rows,
            provenance=provenance,
            role_counts=role_counts,
        )
        if recomputed != spec.content_manifest_sha256:
            raise FitRoleArtifactError("loaded snapshot content-manifest digest differs from spec")
        if str(adata.uns["content_manifest_sha256"]) != spec.content_manifest_sha256:
            raise FitRoleArtifactError("loaded snapshot stored content manifest differs from spec")
        if adata.n_obs != spec.n_cells or adata.n_vars != spec.n_genes:
            raise FitRoleArtifactError("loaded snapshot shape differs from spec")
        if role_counts != spec.role_counts:
            raise FitRoleArtifactError("loaded snapshot role counts differ from spec")
    except FitRoleArtifactError:
        raise
    except Exception as exc:
        raise FitRoleArtifactError(f"malformed loaded fit-role snapshot: {exc!r}") from exc


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

    def _canonical_token(self, pert: str, role: str) -> str:
        """Return the canonical perturbation token to store for a selected row.

        Combo (``combo_calibration``) tokens are rewritten to their byte-canonical
        ``GENEA<sep>GENEB`` form so a non-canonically ordered raw token (e.g.
        ``KLF1_CEBPE``) is stored, hashed, and validated identically to its
        canonical form (spec §3/§3.2/§4). ``control`` and ``singles`` tokens are
        already canonical (the control token / a single gene) and pass through
        unchanged.

        Parameters
        ----------
        pert : str
            The raw obs perturbation token for the row.
        role : str
            The derived fit role of the row.

        Returns
        -------
        str
            The canonical perturbation token to store in the artifact.
        """
        if role == "combo_calibration":
            a, b = _canonical_pair(pert, self._combo_sep)
            return f"{a}{self._combo_sep}{b}"
        return pert

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
        rows = tuple(
            (self._src[i], roles[i], self._canonical_token(self._pert[i], roles[i])) for i in idx
        )
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


def _file_sha256(path: str) -> str:
    """Return the ``"sha256:"``-prefixed hex digest of a file's bytes.

    Parameters
    ----------
    path : str
        Path to the file whose byte content is digested.

    Returns
    -------
    str
        ``"sha256:" + hexdigest`` of the file contents.
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


@dataclass(frozen=True)
class FitRoleArtifactSpec:
    """Immutable identity of a written fit-role artifact (spec §2.1).

    Attributes
    ----------
    path : str
        Filesystem path the artifact was written to.
    sha256 : str
        ``"sha256:"``-prefixed hex digest of the written ``.h5ad`` file bytes.
    content_manifest_sha256 : str
        Storage-layout-invariant logical-content digest (bare hex).
    raw_data_sha256 : str
        Raw-data digest carried from the committed split manifest.
    pair_manifest_sha256 : str
        Verified committed split-manifest checksum.
    eligibility_hash : str
        Outcome-independent eligibility hash from the split manifest.
    row_identity_sha256 : str
        Canonical row-identity digest (bare hex).
    gene_order_sha256 : str
        Canonical gene-order digest (bare hex).
    n_cells : int
        Number of retained (non-sealed) rows written.
    n_genes : int
        Number of genes in the full gene universe.
    role_counts : dict of str to int
        Count of written rows per allowed role.
    """

    path: str
    sha256: str
    content_manifest_sha256: str
    raw_data_sha256: str
    pair_manifest_sha256: str
    eligibility_hash: str
    row_identity_sha256: str
    gene_order_sha256: str
    n_cells: int
    n_genes: int
    role_counts: dict[str, int]

    def to_payload_block(self) -> dict:
        """The spec §2.1 ``fit_role_artifact`` payload block.

        Returns
        -------
        dict
            The serialisable ``fit_role_artifact`` provenance block describing
            this artifact's format, schema version, digests and shape.
        """
        return {
            "format": "anndata_h5ad",
            "artifact_schema_version": _ARTIFACT_SCHEMA_VERSION,
            "path": self.path,
            "sha256": self.sha256,
            "content_manifest_sha256": self.content_manifest_sha256,
            "raw_data_sha256": self.raw_data_sha256,
            "pair_manifest_sha256": self.pair_manifest_sha256,
            "eligibility_hash": self.eligibility_hash,
            "row_identity_sha256": self.row_identity_sha256,
            "role_obs_key": "role",
            "perturbation_obs_key": "perturbation",
            "allowed_obs_roles": ["control", "singles", "combo_calibration"],
            "gene_order_sha256": self.gene_order_sha256,
            "n_cells": int(self.n_cells),
            "n_genes": int(self.n_genes),
            "role_counts": dict(self.role_counts),
            "counts_location": "X",
        }


def generate_fit_role_artifact(
    *,
    extraction: FitRoleExtraction,
    out_path: str,
    config_sha256: str,
    data_card_sha256: str,
    calibration_gene_set_hash: str,
    generator_code_sha256: str,
    writer_environment_sha256: str,
) -> FitRoleArtifactSpec:
    """Write an immutable fit-role ``.h5ad`` and bind its canonical identity.

    The artifact is write-once: the call fails closed if ``out_path`` already
    exists. ``X`` is stored as raw CSR counts (finite, non-negative,
    integer-valued) over the full gene universe; ``obs`` carries
    ``role``/``perturbation``/``source_row_id``; ``uns.provenance`` carries all
    lineage digests and ``uns.content_manifest_sha256`` the logical-content
    digest. After writing, the file is reloaded and its recomputed content
    manifest is checked against the pre-write value (spec §2.1/§3.2/§4).

    Parameters
    ----------
    extraction : FitRoleExtraction
        The allowed-row-only extraction (sealed rows never materialized).
    out_path : str
        Destination ``.h5ad`` path; must not already exist.
    config_sha256 : str
        Resolved-config digest to record in provenance.
    data_card_sha256 : str
        Data-card digest to record in provenance.
    calibration_gene_set_hash : str
        Calibration gene-set hash to record in provenance.
    generator_code_sha256 : str
        Digest of the generator code to record in provenance.
    writer_environment_sha256 : str
        Digest of the writer environment to record in provenance.

    Returns
    -------
    FitRoleArtifactSpec
        The immutable identity of the written artifact.

    Raises
    ------
    FitRoleArtifactError
        If ``out_path`` exists, if ``X`` is not finite/non-negative/integer,
        if a non-whitelisted role is present, or if the read-back content
        manifest does not match the pre-write value.
    """
    import anndata as ad
    import pandas as pd

    if os.path.exists(out_path):
        raise FitRoleArtifactError(f"refusing to overwrite existing artifact: {out_path}")

    X = sparse.csr_matrix(extraction.X)
    data = X.data
    if data.size and (
        not np.all(np.isfinite(data)) or np.any(data < 0) or np.any(data != np.floor(data))
    ):
        raise FitRoleArtifactError("X must be finite, non-negative, integer-valued counts")
    roles = [r for _, r, _ in extraction.rows]
    if not set(roles) <= _ALLOWED_ROLES:
        raise FitRoleArtifactError("extraction carries a non-whitelisted role")

    gene_order_sha256 = canonical_gene_order_sha256(extraction.var_names)
    row_identity = row_identity_sha256(extraction.rows)
    provenance = {
        "data_card_sha256": str(data_card_sha256),
        "raw_data_sha256": extraction.raw_data_sha256,
        "pair_manifest_sha256": extraction.pair_manifest_sha256,
        "eligibility_hash": extraction.eligibility_hash,
        "calibration_gene_set_hash": str(calibration_gene_set_hash),
        "row_identity_sha256": row_identity,
        "gene_order_sha256": gene_order_sha256,
        "generator_code_sha256": str(generator_code_sha256),
        "writer_environment_sha256": str(writer_environment_sha256),
        "config_sha256": str(config_sha256),
    }
    content_manifest = content_manifest_sha256(
        schema_version=_ARTIFACT_SCHEMA_VERSION,
        X=X,
        var_names=extraction.var_names,
        rows=extraction.rows,
        provenance=provenance,
        role_counts=extraction.role_counts,
    )

    obs = pd.DataFrame(
        {
            "role": pd.Categorical(roles, categories=sorted(_ALLOWED_ROLES)),
            "perturbation": [p for _, _, p in extraction.rows],
            "source_row_id": [s for s, _, _ in extraction.rows],
        }
    )
    var = pd.DataFrame(index=list(extraction.var_names))
    adata = ad.AnnData(X=X, obs=obs, var=var)
    adata.uns["provenance"] = provenance
    adata.uns["content_manifest_sha256"] = content_manifest
    adata.write_h5ad(out_path)

    # read-back verification: logical identity must survive the write
    reloaded = ad.read_h5ad(out_path)
    rb_rows = tuple(
        (str(s), str(r), str(p))
        for s, r, p in zip(
            reloaded.obs["source_row_id"],
            reloaded.obs["role"],
            reloaded.obs["perturbation"],
        )
    )
    rb_manifest = content_manifest_sha256(
        schema_version=_ARTIFACT_SCHEMA_VERSION,
        X=sparse.csr_matrix(reloaded.X),
        var_names=[str(v) for v in reloaded.var_names],
        rows=rb_rows,
        provenance=dict(reloaded.uns["provenance"]),
        role_counts=extraction.role_counts,
    )
    if rb_manifest != content_manifest:
        raise FitRoleArtifactError("read-back content manifest mismatch after write")

    return FitRoleArtifactSpec(
        path=out_path,
        sha256=_file_sha256(out_path),
        content_manifest_sha256=content_manifest,
        raw_data_sha256=extraction.raw_data_sha256,
        pair_manifest_sha256=extraction.pair_manifest_sha256,
        eligibility_hash=extraction.eligibility_hash,
        row_identity_sha256=row_identity,
        gene_order_sha256=gene_order_sha256,
        n_cells=X.shape[0],
        n_genes=X.shape[1],
        role_counts=dict(extraction.role_counts),
    )


def _assert_canonical_path(path: str, approved_root: str) -> str:
    """Assert ``path`` is a safe, in-scope regular file and return its real path.

    The path must be absolute + normalized, a regular file (not a symlink), and
    resolve to a location inside ``approved_root`` (spec §5). Fail closed.

    Parameters
    ----------
    path : str
        Candidate artifact path to validate.
    approved_root : str
        Directory the artifact must live inside.

    Returns
    -------
    str
        The canonical (``realpath``) absolute path of the artifact.

    Raises
    ------
    FitRoleArtifactError
        If ``path`` is a symlink, is not a regular file, or escapes
        ``approved_root``.
    """
    ap = os.path.realpath(os.path.abspath(path))
    root = os.path.realpath(os.path.abspath(approved_root))
    if os.path.islink(path):
        raise FitRoleArtifactError(f"artifact path is a symlink: {path}")
    if not os.path.isfile(ap):
        raise FitRoleArtifactError(f"artifact path is not a regular file: {path}")
    if os.path.commonpath([ap, root]) != root:
        raise FitRoleArtifactError(f"artifact path escapes approved_root: {path}")
    return ap


def _required_role_for_token(
    perturbation: str,
    *,
    calib: set[tuple[str, str]],
    sealed: set[tuple[str, str]],
    control_token: str,
    combo_sep: str,
) -> str:
    """Return the fit role every artifact row carrying ``perturbation`` must declare.

    Mirrors :meth:`ComposeFitRoleExtractor._role_of` so validation classifies each
    stored token independently of its declared role: the control token maps to
    ``control``, a canonical registered calibration combo to ``combo_calibration``,
    and any other token to ``singles``. Unlike the extractor it never returns
    ``None`` — a valid fit artifact never stores a sealed combo cell, so a sealed
    pair appearing in obs is a leak and fails closed.

    Parameters
    ----------
    perturbation : str
        The stored obs perturbation token for one row.
    calib : set of tuple of str
        Registered calibration combo pairs (canonical, byte-ordered).
    sealed : set of tuple of str
        Sealed combo pairs; any occurrence in obs is a leak.
    control_token : str
        The token that denotes a control cell.
    combo_sep : str
        Separator between the two single-gene tokens of a combo.

    Returns
    -------
    str
        The required role (``control`` / ``singles`` / ``combo_calibration``).

    Raises
    ------
    FitRoleArtifactError
        If a combo token is non-canonical, sealed, in both pair sets, or
        unregistered — fail closed.
    """
    if perturbation == control_token:
        return "control"
    if combo_sep in perturbation:
        a, b = _canonical_pair(perturbation, combo_sep)
        if perturbation != f"{a}{combo_sep}{b}":
            raise FitRoleArtifactError(f"combo token is not canonical: {perturbation!r}")
        pair = (a, b)
        in_calib = pair in calib
        in_sealed = pair in sealed
        if in_calib and in_sealed:
            raise FitRoleArtifactError(
                f"combo pair {pair!r} is in both calibration and sealed sets"
            )
        if in_sealed:
            raise FitRoleArtifactError(f"sealed pair present in artifact obs: {pair!r}")
        if not in_calib:
            raise FitRoleArtifactError(f"combo pair not in calibration set: {pair!r}")
        return "combo_calibration"
    return "singles"


def validate_fit_role_artifact(
    path: str,
    *,
    spec: FitRoleArtifactSpec,
    approved_root: str,
    calibration_pair_ids: Sequence[tuple[str, str]],
    sealed_pair_ids: Sequence[tuple[str, str]],
    single_gene_ids: Sequence[str],
    control_token: str = "control",
    combo_sep: str = "_",
) -> None:
    """Re-validate a fit-role artifact against its spec before fitting (spec §5).

    Re-reads the artifact from disk and re-checks path policy, the file byte
    digest, per-row role↔token consistency, the binding of the trusted spec to the
    artifact's own provenance/shape, every logical-content identity digest, the
    role closure, and the absence of any sealed combo pair. This is the exact
    guard a worker runs before fit; it fails closed on any mismatch.

    Parameters
    ----------
    path : str
        Filesystem path to the artifact to validate.
    spec : FitRoleArtifactSpec
        The immutable identity the artifact must match.
    approved_root : str
        Directory the artifact must live inside.
    calibration_pair_ids : Sequence of tuple of str
        Registered calibration combo pairs; every combo cell must belong to this
        set.
    sealed_pair_ids : Sequence of tuple of str
        Sealed combo pairs; no cell of any role may carry a sealed pair (a sealed
        pair present in obs is a leak → reject).
    single_gene_ids : Sequence of str
        The governed single-gene universe. Every obs token that classifies as
        ``singles`` must be a member. A sealed/calibration combo written under a
        separator other than ``combo_sep`` (e.g. a real ``GENEA+GENEB`` when
        ``combo_sep`` is ``"_"``) otherwise falls through to ``singles`` and
        smuggles a sealed outcome cell into the fit set; the membership check
        closes that leak independently of separator correctness.
    control_token : str, default ``"control"``
        Token denoting a control cell (A1-consistent default so existing callers
        that pass only the pair sets keep working).
    combo_sep : str, default ``"_"``
        Separator between the two single-gene tokens of a combo (A1-consistent
        default).

    Raises
    ------
    FitRoleArtifactError
        On any path, digest, role↔token, lineage, shape, role-closure, or
        sealed-pair violation, and on any otherwise-unexpected failure from a
        malformed/forged artifact (every failure surfaces as
        ``FitRoleArtifactError`` — fail closed).
    """
    try:
        _validate_fit_role_artifact_checks(
            path,
            spec=spec,
            approved_root=approved_root,
            calibration_pair_ids=calibration_pair_ids,
            sealed_pair_ids=sealed_pair_ids,
            single_gene_ids=single_gene_ids,
            control_token=control_token,
            combo_sep=combo_sep,
        )
    except FitRoleArtifactError:
        raise
    except Exception as exc:  # fail closed: any malformed/forged artifact
        raise FitRoleArtifactError(f"malformed fit-role artifact: {exc!r}") from exc


def _validate_fit_role_artifact_checks(
    path: str,
    *,
    spec: FitRoleArtifactSpec,
    approved_root: str,
    calibration_pair_ids: Sequence[tuple[str, str]],
    sealed_pair_ids: Sequence[tuple[str, str]],
    single_gene_ids: Sequence[str],
    control_token: str = "control",
    combo_sep: str = "_",
) -> None:
    """Run every fit-role validation check; raise on the first violation.

    Extracted from :func:`validate_fit_role_artifact` so the public entry point
    can uniformly re-raise any non-:class:`FitRoleArtifactError` failure (e.g. a
    ``KeyError``/``ValueError`` from a malformed or forged ``.h5ad``) as a
    :class:`FitRoleArtifactError` — everything fails closed (spec §5).
    """
    import anndata as ad

    resolved = _assert_canonical_path(path, approved_root)
    if _file_sha256(resolved) != spec.sha256:
        raise FitRoleArtifactError("artifact file SHA mismatch")

    adata = ad.read_h5ad(resolved)
    roles = [str(r) for r in adata.obs["role"]]
    if not set(roles) <= _ALLOWED_ROLES:
        raise FitRoleArtifactError(f"non-whitelisted roles: {set(roles) - _ALLOWED_ROLES}")

    calib = {tuple(p) for p in calibration_pair_ids}
    sealed = {tuple(p) for p in sealed_pair_ids}
    perts = [str(p) for p in adata.obs["perturbation"]]
    srcs = [str(s) for s in adata.obs["source_row_id"]]

    single_list = [str(g) for g in single_gene_ids]
    single_set = set(single_list)
    if not single_list or len(single_set) != len(single_list) or any(g == "" for g in single_list):
        raise FitRoleArtifactError("single_gene_ids must be a non-empty unique list of gene ids")

    # role↔token: classify EVERY row independently of its declared role (spec
    # §7.1; mirrors ComposeFitRoleExtractor._role_of). A sealed combo mislabeled
    # `singles`/`control`, a non-canonical combo, or an unregistered combo all
    # fail closed here — the check is NOT gated on role == "combo_calibration".
    for role, pert in zip(roles, perts):
        expected = _required_role_for_token(
            pert, calib=calib, sealed=sealed, control_token=control_token, combo_sep=combo_sep
        )
        if role != expected:
            raise FitRoleArtifactError(
                f"role/token mismatch: token {pert!r} requires role {expected!r}, got {role!r}"
            )
        # A token that classifies as `singles` MUST be a registered single-gene id.
        # A sealed/calibration combo written under a separator other than
        # `combo_sep` (e.g. a real `GENEA+GENEB` when `combo_sep` is `_`) falls
        # through to `singles` and would smuggle a sealed outcome cell into the fit
        # set; this membership check closes that leak regardless of `combo_sep`.
        if expected == "singles" and pert not in single_set:
            raise FitRoleArtifactError(
                f"token {pert!r} classified 'singles' is not a registered single-gene id"
            )

    observed_singles = {pert for role, pert in zip(roles, perts) if role == "singles"}
    if observed_singles != single_set:
        missing = sorted(single_set - observed_singles, key=lambda value: value.encode("utf-8"))
        extra = sorted(observed_singles - single_set, key=lambda value: value.encode("utf-8"))
        raise FitRoleArtifactError(
            "fit-role artifact singles roster differs from single_gene_ids "
            f"(missing={missing}, extra={extra})"
        )

    # non-empty, unique source_row_id before recomputing row/content digests
    if any(s == "" for s in srcs):
        raise FitRoleArtifactError("source_row_id must be non-empty")
    if len(set(srcs)) != len(srcs):
        raise FitRoleArtifactError("source_row_id must be unique")

    var_names = [str(v) for v in adata.var_names]
    rows = tuple((s, r, p) for s, r, p in zip(srcs, roles, perts))
    role_counts = {r: sum(1 for _, rr, _ in rows if rr == r) for r in sorted(_ALLOWED_ROLES)}
    if canonical_gene_order_sha256(var_names) != spec.gene_order_sha256:
        raise FitRoleArtifactError("gene_order digest mismatch")
    if row_identity_sha256(rows) != spec.row_identity_sha256:
        raise FitRoleArtifactError("row_identity digest mismatch")

    # bind the independently trusted spec to the artifact's OWN provenance/shape so
    # a spec cannot advertise false lineage while pointing at a valid-but-different
    # artifact (the content manifest is recomputed from this same provenance).
    provenance = dict(adata.uns["provenance"])
    for key in ("raw_data_sha256", "pair_manifest_sha256", "eligibility_hash"):
        if str(provenance[key]) != str(getattr(spec, key)):
            raise FitRoleArtifactError(f"{key} differs between spec and artifact provenance")
    if str(provenance["row_identity_sha256"]) != spec.row_identity_sha256:
        raise FitRoleArtifactError("provenance row_identity_sha256 mismatch")
    if str(provenance["gene_order_sha256"]) != spec.gene_order_sha256:
        raise FitRoleArtifactError("provenance gene_order_sha256 mismatch")

    recomputed = content_manifest_sha256(
        schema_version=_ARTIFACT_SCHEMA_VERSION,
        X=sparse.csr_matrix(adata.X),
        var_names=var_names,
        rows=rows,
        provenance=provenance,
        role_counts=role_counts,
    )
    if recomputed != spec.content_manifest_sha256:
        raise FitRoleArtifactError("content_manifest digest mismatch")
    if str(adata.uns["content_manifest_sha256"]) != spec.content_manifest_sha256:
        raise FitRoleArtifactError("stored content_manifest_sha256 differs from spec")
    if adata.n_obs != spec.n_cells or adata.n_vars != spec.n_genes:
        raise FitRoleArtifactError("artifact shape differs from spec")
    if role_counts != spec.role_counts:
        raise FitRoleArtifactError("artifact role_counts differ from spec")


def build_response_projection(
    response_space: ResponseSpace,
    *,
    gene_order: Sequence[str],
    control_mean: Sequence[float] | np.ndarray,
    raw_data_sha256: str,
) -> dict:
    """Serialize a ``ResponseSpace`` into the spec §2.2 ``response_projection`` block.

    The block is the single-source-of-truth native→PCA-50 operator a worker
    applies to its full-gene predictions. ``verify_response_artifact`` re-checks
    the space checksum and yields the combined (space + control_mean) digest used
    as ``response_artifact_sha256``.

    Parameters
    ----------
    response_space : ResponseSpace
        The frozen, checksum-sealed response space (its ``_control_mean`` may be
        ``None``; the z-space centroid is supplied separately).
    gene_order : sequence of str
        Canonical full gene-ID order the space was fit against; ``hvg_idx`` maps
        into it to name the HVGs and to bind ``gene_order_sha256``.
    control_mean : sequence of float
        z-space control centroid, length ``pca_dim``.
    raw_data_sha256 : str
        Exact raw-data digest, embedded for cross-source equality (spec §2.2).

    Returns
    -------
    dict
        The ``response_projection`` block (spec §2.2).

    Raises
    ------
    FitRoleArtifactError
        On a checksum/shape/range/finiteness violation.
    """
    genes = _check_gene_ids(gene_order)
    try:
        snapshot, ctrl, combined = verify_response_artifact(response_space, control_mean)
    except ValueError as exc:
        raise FitRoleArtifactError(f"invalid response space: {exc}") from exc

    n_hvg = int(snapshot.n_hvg)
    pca_dim = int(snapshot.pca_dim)
    hvg_idx = np.asarray(snapshot.hvg_idx, dtype=np.int64)
    if hvg_idx.shape != (n_hvg,):
        raise FitRoleArtifactError("hvg_idx does not match n_hvg")
    if hvg_idx.min(initial=0) < 0 or (hvg_idx.size and int(hvg_idx.max()) >= len(genes)):
        raise FitRoleArtifactError("hvg_idx out of range for the given gene_order")
    pca_components = np.asarray(snapshot.pca_components, dtype=np.float64)
    pca_mean = np.asarray(snapshot.pca_mean, dtype=np.float64)
    if pca_components.shape != (pca_dim, n_hvg):
        raise FitRoleArtifactError("pca_components shape does not match (pca_dim, n_hvg)")
    if pca_mean.shape != (n_hvg,):
        raise FitRoleArtifactError("pca_mean length does not match n_hvg")
    if ctrl.shape != (pca_dim,):
        raise FitRoleArtifactError("control_mean must be a pca_dim vector")
    if not (
        np.all(np.isfinite(pca_components))
        and np.all(np.isfinite(pca_mean))
        and np.all(np.isfinite(ctrl))
    ):
        raise FitRoleArtifactError("projection arrays must be finite")

    return {
        "response_artifact_sha256": str(combined),
        "raw_data_sha256": str(raw_data_sha256),
        "gene_order_sha256": canonical_gene_order_sha256(genes),
        "hvg_gene_ids": [genes[int(i)] for i in hvg_idx],
        "transform": list(RESPONSE_TRANSFORM),
        "median_library": float(snapshot.median_library),
        "pca_mean": pca_mean.tolist(),
        "pca_components": pca_components.tolist(),
        "control_mean": ctrl.tolist(),
        "delta_convention": "z_minus_control_mean",
    }


PREDICTION_REPRESENTATIONS: frozenset[str] = frozenset(
    {"cell_raw_counts", "cell_log_normalized", "raw_pseudobulk_approximation"}
)


def _normalize_log1p_full(x: np.ndarray, median_library: float) -> np.ndarray:
    """Frozen library-size normalize to ``median_library`` then ``log1p``.

    Identical arithmetic to ``response._normalize_log1p`` so the worker-side
    operator reproduces ``ResponseSpace.project`` exactly.
    """
    lib = x.sum(axis=1, keepdims=True)
    safe = np.where(lib > 0, lib, 1.0)
    return np.log1p(x * (median_library / safe))


def apply_response_projection(
    block: Mapping,
    x_native: np.ndarray,
    gene_order: Sequence[str],
    *,
    representation: str,
) -> np.ndarray:
    """Reconstruct the spec §2.3 operator ``z(x)`` for full-gene rows (pure numpy).

    ``cell_raw_counts`` and ``raw_pseudobulk_approximation`` apply the full frozen
    transform (normalize to ``median_library`` + ``log1p``) then HVG subset +
    centering + PCA projection; ``cell_log_normalized`` skips the raw transform
    because the caller already log-normalized at the same ``median_library``.
    Truth δ (``mean(z) - control_mean``) is computed by the caller and is
    invariant to ``representation`` (spec §2.4).

    Parameters
    ----------
    block : Mapping
        A ``response_projection`` block (spec §2.2).
    x_native : numpy.ndarray
        Rows over the full ``gene_order``: raw counts for ``cell_raw_counts`` /
        ``raw_pseudobulk_approximation``; log-normalized values for
        ``cell_log_normalized``. Shape ``(n_rows, n_genes)``.
    gene_order : sequence of str
        The full gene-ID order of ``x_native``; must match the block's
        ``gene_order_sha256``.
    representation : str
        One of :data:`PREDICTION_REPRESENTATIONS`.

    Returns
    -------
    numpy.ndarray
        Projected z-coordinates, shape ``(n_rows, pca_dim)``.

    Raises
    ------
    FitRoleArtifactError
        On an unknown representation, a gene-order digest mismatch, or a shape
        mismatch.
    """
    if representation not in PREDICTION_REPRESENTATIONS:
        raise FitRoleArtifactError(f"unknown prediction representation: {representation!r}")
    genes = [str(g) for g in gene_order]
    if canonical_gene_order_sha256(genes) != block["gene_order_sha256"]:
        raise FitRoleArtifactError("gene_order digest mismatch for projection")
    X = np.asarray(x_native, dtype=np.float64)
    if X.ndim != 2 or X.shape[1] != len(genes):
        raise FitRoleArtifactError("x_native must be (n_rows, n_genes) over the full gene order")
    if not np.all(np.isfinite(X)):
        raise FitRoleArtifactError("x_native must contain only finite values")
    if np.any(X < 0):
        raise FitRoleArtifactError("registered native/log1p representations must be non-negative")

    if representation == "cell_log_normalized":
        normed = X
    else:
        normed = _normalize_log1p_full(X, float(block["median_library"]))

    name_to_col = {g: i for i, g in enumerate(genes)}
    hvg_gene_ids = list(block["hvg_gene_ids"])
    try:
        hvg_cols = [name_to_col[g] for g in hvg_gene_ids]
    except KeyError as exc:
        raise FitRoleArtifactError(f"hvg gene {exc} absent from gene_order") from exc
    sub = normed[:, hvg_cols]
    pca_mean = np.asarray(block["pca_mean"], dtype=np.float64)
    pca_components = np.asarray(block["pca_components"], dtype=np.float64)
    if pca_mean.shape != (len(hvg_cols),):
        raise FitRoleArtifactError("pca_mean is not aligned with hvg_gene_ids")
    if pca_components.ndim != 2 or pca_components.shape[1] != len(hvg_cols):
        raise FitRoleArtifactError("pca_components are not aligned with hvg_gene_ids")
    if not np.all(np.isfinite(pca_mean)) or not np.all(np.isfinite(pca_components)):
        raise FitRoleArtifactError("projection arrays must be finite")
    return (sub - pca_mean) @ pca_components.T
