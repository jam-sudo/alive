"""Fixed per-gene factor construction for COMPOSE Phase 2a (Task 2a-4).

For each registered ``k_total`` this module builds a per-gene factor vector

.. math::

    z_g = [\\,\\mathrm{PCA_{expr}}(\\delta_g,\\ k_{total}-d_{esm})\\;;\\;
            \\mathrm{PCA_{esm}}(s_g,\\ d_{esm})\\,]

where:

- :math:`\\delta_g` is the eligible single-gene expression shift (a *single-role*
  quantity, allowed under plan §2.4 because the confirmatory claim is
  pair/combo-zero-shot, not single-gene-zero-shot);
- :math:`s_g` is the gene's raw ESM sequence vector. The ESM projection is
  **outcome-free**: it is fitted on eligible sequence vectors only and never
  touches any expression outcome, single or double.

Leakage boundary (plan §2.1): ``z`` is a pure function of the singles' ``delta``
and the ESM sequences. There is no public parameter that can carry a double /
combination outcome, and the function rejects unknown keywords, so no combo
outcome can ever influence a factor.

Determinism / orientation policy
--------------------------------
PCA component signs are arbitrary (SVD sign degeneracy). The registered policy,
identical to :mod:`alive.compose.response`, fixes each component's sign so that
its **largest-magnitude loading is positive** (ties broken by the lowest index).
This makes ``z`` deterministic and byte-reproducible across runs and platforms
for a given set of input vectors: the same inputs always yield the same scores,
independent of the raw SVD sign convention returned by the backend.

Provenance
----------
Each :class:`GeneFactorBank` records the canonical (UTF-8-sorted) gene ordering,
the orientation policy string, expression and ESM explained-variance vectors, the
encoder revision, the sequence-mapping hash, and a self-excluding SHA-256
``checksum`` over the canonical artifact payload (reusing
:func:`alive.provenance.sha256_bytes` / :func:`alive.provenance.sha256_json`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

import numpy as np
from numpy.typing import NDArray
from sklearn.decomposition import PCA

from alive.provenance import sha256_bytes, sha256_json

ZFACTOR_ALGORITHM = "compose_zfactor_pca"
ZFACTOR_VERSION = "2a.1"

#: Registered, deterministic PCA sign convention.
ORIENTATION_POLICY = "sign_of_largest_magnitude_loading_positive"

#: Default ESM projection dimension (config ``factor_z.esm_projection_dim``).
DEFAULT_ESM_DIM = 2

#: On-disk collection schema used by scientific stage-1 carriers.  A collection
#: is deliberately separate from an individual bank's self-checksummed report:
#: the former binds the exact registered k-grid and aggregate factor checksum,
#: while the latter remains the canonical per-k provenance artifact.
FACTOR_BANK_COLLECTION_SCHEMA = "compose_factor_bank_collection_v1"


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GeneFactorBank:
    """A frozen per-gene factor bank for a single ``k_total``.

    The bank stores the per-gene factor vectors plus the provenance needed to
    audit how they were built. The ``checksum`` is a self-excluding SHA-256 over
    the canonical payload; it changes if and only if a factor value, a fitted
    statistic, a dimension or a recorded provenance field changes.

    Attributes
    ----------
    k_total : int
        Total factor dimension (``expression_dim + esm_dim``).
    expression_dim : int
        Number of expression-PCA components (``k_total - esm_dim``).
    esm_dim : int
        Number of ESM-PCA components.
    gene_order : tuple of str
        Canonical UTF-8-sorted gene ordering used for every fit and report.
    z_by_gene : dict
        Mapping ``gene -> z`` where ``z`` has length ``k_total``
        (expression block first, ESM block second).
    expression_explained_variance : numpy.ndarray
        Per-component explained variance of the expression PCA,
        shape ``(expression_dim,)``.
    esm_explained_variance : numpy.ndarray
        Per-component explained variance of the ESM PCA, shape ``(esm_dim,)``.
    expression_components : numpy.ndarray
        Sign-oriented expression-PCA loadings, shape ``(expression_dim, delta_dim)``.
        Each row's largest-magnitude loading is positive (orientation policy).
    esm_components : numpy.ndarray
        Sign-oriented ESM-PCA loadings, shape ``(esm_dim, esm_dim_raw)``.
    encoder_revision : str
        ESM encoder model revision the sequence vectors were produced with.
    sequence_mapping_hash : str
        Hash of the gene->protein-sequence mapping used for the ESM vectors.
    checksum : str
        Self-excluding SHA-256 over the canonical artifact payload.
    """

    k_total: int
    expression_dim: int
    esm_dim: int
    gene_order: tuple[str, ...]
    z_by_gene: dict[str, NDArray[np.float64]]
    expression_explained_variance: NDArray[np.float64]
    esm_explained_variance: NDArray[np.float64]
    expression_components: NDArray[np.float64]
    esm_components: NDArray[np.float64]
    encoder_revision: str
    sequence_mapping_hash: str
    checksum: str = field(default="")

    # -- provenance -------------------------------------------------------

    def _payload(self) -> dict:
        """Canonical, JSON-serialisable artifact payload (checksum input)."""
        return {
            "algorithm": ZFACTOR_ALGORITHM,
            "version": ZFACTOR_VERSION,
            "orientation_policy": ORIENTATION_POLICY,
            "k_total": int(self.k_total),
            "expression_dim": int(self.expression_dim),
            "esm_dim": int(self.esm_dim),
            "gene_order": list(self.gene_order),
            "z_by_gene": {g: _round_array(self.z_by_gene[g]) for g in self.gene_order},
            "expression_explained_variance": _round_array(self.expression_explained_variance),
            "esm_explained_variance": _round_array(self.esm_explained_variance),
            "expression_components": _round_array(self.expression_components),
            "esm_components": _round_array(self.esm_components),
            "encoder_revision": self.encoder_revision,
            "sequence_mapping_hash": self.sequence_mapping_hash,
        }

    def artifact_bytes(self) -> bytes:
        """Canonical bytes of the artifact payload (excludes the checksum)."""
        return json.dumps(self._payload(), sort_keys=True, separators=(",", ":")).encode("utf-8")

    def report(self) -> dict:
        """Serialisable provenance report.

        Returns
        -------
        dict
            The canonical payload augmented with the self-excluding ``checksum``.
            Contains the gene ordering, orientation policy, explained variance,
            encoder revision and sequence-mapping hash required by the brief.
        """
        rep = self._payload()
        rep["checksum"] = self.checksum
        return rep


def serialize_factor_bank_collection(
    factor_banks_by_k: Mapping[int, GeneFactorBank],
) -> dict[str, Any]:
    """Return the canonical scientific-carrier representation of factor banks.

    Every individual checksum is independently recomputed before any bytes are
    emitted.  The collection checksum is the same aggregate digest consumed by
    :func:`alive.compose.phase2a._verify_factor_banks`, so the stage-1 artifact,
    ``Phase2aInputs.factor_checksum`` and the runtime matrices share one identity.
    """
    if not factor_banks_by_k:
        raise ValueError("factor_banks_by_k must be non-empty")
    banks: dict[int, GeneFactorBank] = {}
    for raw_k, bank in factor_banks_by_k.items():
        if isinstance(raw_k, bool) or not isinstance(raw_k, (int, np.integer)):
            raise ValueError(f"factor-bank key must be an integer, got {raw_k!r}")
        k_total = int(raw_k)
        if k_total in banks:
            raise ValueError(f"duplicate factor-bank key after integer normalization: {k_total}")
        if not isinstance(bank, GeneFactorBank):
            raise TypeError(f"factor bank k={k_total} is not a GeneFactorBank")
        if int(bank.k_total) != k_total:
            raise ValueError(
                f"factor-bank key {k_total} disagrees with bank.k_total={bank.k_total}"
            )
        observed = sha256_bytes(bank.artifact_bytes())
        if observed != bank.checksum:
            raise ValueError(
                f"factor bank k={k_total} checksum does not verify: "
                f"declared={bank.checksum!r}, observed={observed!r}"
            )
        banks[k_total] = bank

    aggregate = sha256_json(
        {"factor_banks_by_k": {str(k): banks[k].checksum for k in sorted(banks)}}
    )
    reports = {str(k): _lossless_carrier_report(banks[k]) for k in sorted(banks)}
    for report in reports.values():
        _deserialize_gene_factor_bank(report)
    return {
        "schema": FACTOR_BANK_COLLECTION_SCHEMA,
        "factor_checksum": aggregate,
        "k_grid": [int(k) for k in sorted(banks)],
        "factor_banks_by_k": reports,
    }


def _lossless_carrier_report(bank: GeneFactorBank) -> dict[str, Any]:
    """Return a checksummed report whose numeric arrays round-trip exactly.

    ``GeneFactorBank.report`` intentionally rounds numeric payloads to 12 decimal
    places for a stable scientific checksum.  A runtime carrier has a second,
    stricter need: its factor matrix must remain byte-for-byte equal to the bank
    rows after JSON reconstruction.  Preserve the original float64 values in the
    collection while retaining the registered rounded checksum semantics.
    """
    report = bank.report()
    report["z_by_gene"] = {
        gene: np.asarray(bank.z_by_gene[gene], dtype=np.float64).tolist()
        for gene in bank.gene_order
    }
    report["expression_explained_variance"] = np.asarray(
        bank.expression_explained_variance, dtype=np.float64
    ).tolist()
    report["esm_explained_variance"] = np.asarray(
        bank.esm_explained_variance, dtype=np.float64
    ).tolist()
    report["expression_components"] = np.asarray(
        bank.expression_components, dtype=np.float64
    ).tolist()
    report["esm_components"] = np.asarray(bank.esm_components, dtype=np.float64).tolist()
    return report


def deserialize_factor_bank_collection(
    payload: Mapping[str, Any],
) -> tuple[dict[int, GeneFactorBank], str]:
    """Strictly reconstruct and authenticate a scientific factor-bank collection.

    The loader accepts no derived defaults: schema fields, shapes, gene ordering,
    per-bank checksums, k-grid identity and aggregate checksum must all agree.
    This makes a carrier load fail before Phase 2a if a bank is missing, reordered,
    truncated or edited independently from its registered factor matrices.
    """
    expected_collection_keys = {
        "schema",
        "factor_checksum",
        "k_grid",
        "factor_banks_by_k",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected_collection_keys:
        raise ValueError(
            f"factor-bank collection keys must be exactly {sorted(expected_collection_keys)!r}"
        )
    if payload["schema"] != FACTOR_BANK_COLLECTION_SCHEMA:
        raise ValueError(f"unsupported factor-bank collection schema {payload['schema']!r}")

    raw_banks = payload["factor_banks_by_k"]
    if not isinstance(raw_banks, Mapping) or not raw_banks:
        raise ValueError("factor_banks_by_k must be a non-empty object")
    banks: dict[int, GeneFactorBank] = {}
    for raw_key, report in raw_banks.items():
        if not isinstance(raw_key, str) or not raw_key.isdecimal():
            raise ValueError(f"factor-bank collection key must be a decimal string: {raw_key!r}")
        k_total = int(raw_key)
        if raw_key != str(k_total) or k_total in banks:
            raise ValueError(f"non-canonical or duplicate factor-bank key {raw_key!r}")
        bank = _deserialize_gene_factor_bank(report)
        if bank.k_total != k_total:
            raise ValueError(
                f"factor-bank key {k_total} disagrees with report k_total={bank.k_total}"
            )
        banks[k_total] = bank

    raw_grid = payload["k_grid"]
    if not isinstance(raw_grid, list) or any(
        isinstance(k, bool) or not isinstance(k, int) for k in raw_grid
    ):
        raise ValueError("factor-bank k_grid must be a list of integers")
    expected_grid = sorted(banks)
    if raw_grid != expected_grid:
        raise ValueError(
            f"factor-bank k_grid {raw_grid!r} does not match bank keys {expected_grid!r}"
        )

    aggregate = sha256_json(
        {"factor_banks_by_k": {str(k): banks[k].checksum for k in expected_grid}}
    )
    if payload["factor_checksum"] != aggregate:
        raise ValueError(
            "factor-bank aggregate checksum does not verify: "
            f"declared={payload['factor_checksum']!r}, observed={aggregate!r}"
        )
    return banks, aggregate


def _deserialize_gene_factor_bank(report: Any) -> GeneFactorBank:
    """Reconstruct one bank from its exact, self-checksummed report."""
    payload_keys = {
        "algorithm",
        "version",
        "orientation_policy",
        "k_total",
        "expression_dim",
        "esm_dim",
        "gene_order",
        "z_by_gene",
        "expression_explained_variance",
        "esm_explained_variance",
        "expression_components",
        "esm_components",
        "encoder_revision",
        "sequence_mapping_hash",
        "checksum",
    }
    if not isinstance(report, Mapping) or set(report) != payload_keys:
        raise ValueError(f"factor-bank report keys must be exactly {sorted(payload_keys)!r}")
    if report["algorithm"] != ZFACTOR_ALGORITHM or report["version"] != ZFACTOR_VERSION:
        raise ValueError("factor-bank algorithm/version does not match the registered contract")
    if report["orientation_policy"] != ORIENTATION_POLICY:
        raise ValueError("factor-bank orientation policy does not match the registered contract")

    dimensions: list[int] = []
    for name in ("k_total", "expression_dim", "esm_dim"):
        value = report[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"factor-bank {name} must be a non-negative integer")
        dimensions.append(int(value))
    k_total, expression_dim, esm_dim = dimensions
    if k_total <= 0 or expression_dim + esm_dim != k_total:
        raise ValueError("factor-bank dimensions must satisfy k_total > 0 and expr + esm = total")

    raw_order = report["gene_order"]
    if (
        not isinstance(raw_order, list)
        or not raw_order
        or any(not isinstance(gene, str) or not gene for gene in raw_order)
    ):
        raise ValueError("factor-bank gene_order must be a non-empty list of non-empty strings")
    gene_order = tuple(raw_order)
    if len(set(gene_order)) != len(gene_order) or gene_order != tuple(
        sorted(gene_order, key=lambda gene: gene.encode("utf-8"))
    ):
        raise ValueError("factor-bank gene_order must be unique and UTF-8 sorted")
    raw_z = report["z_by_gene"]
    if not isinstance(raw_z, Mapping) or set(raw_z) != set(gene_order):
        raise ValueError("factor-bank z_by_gene keys must exactly match gene_order")
    z_by_gene = {
        gene: _validated_factor_array(raw_z[gene], f"z_by_gene[{gene!r}]", (k_total,))
        for gene in gene_order
    }
    expression_variance = _validated_factor_array(
        report["expression_explained_variance"],
        "expression_explained_variance",
        (expression_dim,),
    )
    esm_variance = _validated_factor_array(
        report["esm_explained_variance"], "esm_explained_variance", (esm_dim,)
    )
    if np.any(expression_variance < 0.0) or np.any(esm_variance < 0.0):
        raise ValueError("factor-bank explained variances must be non-negative")
    expression_components = _validated_factor_matrix(
        report["expression_components"], "expression_components", expression_dim
    )
    esm_components = _validated_factor_matrix(report["esm_components"], "esm_components", esm_dim)
    encoder_revision = report["encoder_revision"]
    sequence_mapping_hash = report["sequence_mapping_hash"]
    checksum = report["checksum"]
    if not isinstance(encoder_revision, str) or not encoder_revision:
        raise ValueError("factor-bank encoder_revision must be a non-empty string")
    if not _is_sha256_hex(sequence_mapping_hash):
        raise ValueError("factor-bank sequence_mapping_hash must be a 64-hex SHA-256 digest")
    if not _is_sha256_hex(checksum):
        raise ValueError("factor-bank checksum must be a 64-character SHA-256 hex string")

    bank = GeneFactorBank(
        k_total=k_total,
        expression_dim=expression_dim,
        esm_dim=esm_dim,
        gene_order=gene_order,
        z_by_gene=z_by_gene,
        expression_explained_variance=expression_variance,
        esm_explained_variance=esm_variance,
        expression_components=expression_components,
        esm_components=esm_components,
        encoder_revision=encoder_revision,
        sequence_mapping_hash=sequence_mapping_hash,
        checksum=checksum,
    )
    observed = sha256_bytes(bank.artifact_bytes())
    if observed != checksum:
        raise ValueError(
            f"factor-bank checksum does not verify: declared={checksum!r}, observed={observed!r}"
        )
    return bank


def _validated_factor_array(value: Any, name: str, shape: tuple[int, ...]) -> NDArray[np.float64]:
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"factor-bank {name} is not numeric") from exc
    if array.shape != shape or not np.all(np.isfinite(array)):
        raise ValueError(
            f"factor-bank {name} must have finite shape {shape!r}, got {array.shape!r}"
        )
    return np.ascontiguousarray(array)


def _validated_factor_matrix(value: Any, name: str, n_rows: int) -> NDArray[np.float64]:
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"factor-bank {name} is not numeric") from exc
    if n_rows == 0 and array.size == 0:
        return np.empty((0, 0), dtype=np.float64)
    if (
        array.ndim != 2
        or array.shape[0] != n_rows
        or array.shape[1] == 0
        or not np.all(np.isfinite(array))
    ):
        raise ValueError(
            f"factor-bank {name} must be a finite 2-D matrix with {n_rows} rows, "
            f"got {array.shape!r}"
        )
    return np.ascontiguousarray(array)


def _is_sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def build_gene_factors(
    *,
    delta_by_gene: dict[str, NDArray],
    sequence_by_gene: dict[str, NDArray],
    k_total: int,
    esm_dim: int = DEFAULT_ESM_DIM,
    encoder_revision: str,
    sequence_mapping_hash: str,
) -> GeneFactorBank:
    """Build the fixed per-gene factor bank for a single ``k_total``.

    Parameters
    ----------
    delta_by_gene : dict
        Mapping ``gene -> delta_g`` of eligible single-gene expression shifts.
        All vectors must share the same length. This is a single-role quantity
        (allowed); it must contain no double/combination outcomes.
    sequence_by_gene : dict
        Mapping ``gene -> s_g`` of raw ESM sequence vectors (outcome-free). Must
        cover exactly the same gene set as ``delta_by_gene``; all vectors share a
        common length.
    k_total : int
        Total factor dimension. Must satisfy ``k_total > esm_dim`` (i.e. the
        expression block ``k_total - esm_dim`` is strictly positive).
    esm_dim : int, optional
        Number of ESM-PCA components. Defaults to ``2``. Must satisfy
        ``0 < esm_dim < k_total``.
    encoder_revision : str
        ESM encoder model revision (recorded in provenance).
    sequence_mapping_hash : str
        Hash of the gene->protein-sequence mapping (recorded in provenance).

    Returns
    -------
    GeneFactorBank
        The frozen, checksum-sealed factor bank for this ``k_total``.

    Raises
    ------
    ValueError
        If the dimension arithmetic is infeasible (``esm_dim >= k_total`` or
        ``esm_dim <= 0``), the gene sets of the two inputs disagree, any vector
        is ragged/non-finite, or there are too few genes to fit the requested
        number of components.
    KeyError
        If a gene present in one input is missing its feature in the other.
    """
    # (0) dimension arithmetic -------------------------------------------
    if esm_dim <= 0:
        raise ValueError(f"esm_dim must be positive, got {esm_dim}")
    if esm_dim >= k_total:
        raise ValueError(
            f"esm_dim ({esm_dim}) must be strictly less than k_total ({k_total}); "
            "the expression block (k_total - esm_dim) must be positive"
        )
    expression_dim = k_total - esm_dim

    # (1) canonical gene ordering + fail-closed feature coverage ----------
    gene_order = _canonical_gene_order(delta_by_gene, sequence_by_gene)
    n_genes = len(gene_order)

    # (2) assemble fit matrices in canonical order (fail closed on shape) -
    delta_mat = _stack(delta_by_gene, gene_order, name="delta")
    seq_mat = _stack(sequence_by_gene, gene_order, name="sequence")

    if not (0 < expression_dim <= min(n_genes, delta_mat.shape[1])):
        raise ValueError(
            f"expression_dim must satisfy 0 < expression_dim <= "
            f"min(n_genes={n_genes}, delta_dim={delta_mat.shape[1]}), got {expression_dim}"
        )
    if not (0 < esm_dim <= min(n_genes, seq_mat.shape[1])):
        raise ValueError(
            f"esm_dim must satisfy 0 < esm_dim <= "
            f"min(n_genes={n_genes}, esm_dim_raw={seq_mat.shape[1]}), got {esm_dim}"
        )

    # (3) expression PCA on eligible single-gene shifts (single-role) -----
    expr_scores, expr_var, expr_comp = _fit_pca_scores(delta_mat, expression_dim)

    # (4) ESM PCA — OUTCOME-FREE, on eligible sequence vectors only --------
    esm_scores, esm_var, esm_comp = _fit_pca_scores(seq_mat, esm_dim)

    # (5) concatenate [expression ; ESM] per gene -------------------------
    z_full = np.concatenate([expr_scores, esm_scores], axis=1)
    z_by_gene = {gene: np.ascontiguousarray(z_full[i]) for i, gene in enumerate(gene_order)}

    bank = GeneFactorBank(
        k_total=int(k_total),
        expression_dim=int(expression_dim),
        esm_dim=int(esm_dim),
        gene_order=tuple(gene_order),
        z_by_gene=z_by_gene,
        expression_explained_variance=expr_var,
        esm_explained_variance=esm_var,
        expression_components=expr_comp,
        esm_components=esm_comp,
        encoder_revision=str(encoder_revision),
        sequence_mapping_hash=str(sequence_mapping_hash),
    )
    checksum = sha256_bytes(bank.artifact_bytes())
    return _with_checksum(bank, checksum)


def build_factor_grid(
    *,
    delta_by_gene: dict[str, NDArray],
    sequence_by_gene: dict[str, NDArray],
    total_k_grid: tuple[int, ...],
    esm_dim: int = DEFAULT_ESM_DIM,
    encoder_revision: str,
    sequence_mapping_hash: str,
) -> dict[int, GeneFactorBank]:
    """Build a factor bank for every ``k_total`` in the registered grid.

    Parameters
    ----------
    delta_by_gene, sequence_by_gene : dict
        See :func:`build_gene_factors`.
    total_k_grid : tuple of int
        Registered total-dimension grid (e.g. ``(4, 6, 8)``). Each entry yields
        an expression block of size ``k - esm_dim``.
    esm_dim : int, optional
        ESM projection dimension shared across the grid. Defaults to ``2``.
    encoder_revision, sequence_mapping_hash : str
        Provenance fields forwarded to each bank.

    Returns
    -------
    dict
        Mapping ``k_total -> GeneFactorBank`` for each requested ``k_total``.

    Raises
    ------
    ValueError
        If any ``k_total`` is infeasible (propagated from
        :func:`build_gene_factors`).
    """
    banks: dict[int, GeneFactorBank] = {}
    for k_total in total_k_grid:
        banks[int(k_total)] = build_gene_factors(
            delta_by_gene=delta_by_gene,
            sequence_by_gene=sequence_by_gene,
            k_total=k_total,
            esm_dim=esm_dim,
            encoder_revision=encoder_revision,
            sequence_mapping_hash=sequence_mapping_hash,
        )
    return banks


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _with_checksum(bank: GeneFactorBank, checksum: str) -> GeneFactorBank:
    """Return ``bank`` with its ``checksum`` field set (frozen dataclass)."""
    object.__setattr__(bank, "checksum", checksum)
    return bank


def _canonical_gene_order(
    delta_by_gene: dict[str, NDArray],
    sequence_by_gene: dict[str, NDArray],
) -> list[str]:
    """Return the canonical UTF-8-sorted gene list, failing closed on mismatch.

    Both inputs must cover exactly the same gene set; any gene present in one but
    not the other raises :class:`KeyError`. The ordering is the deterministic
    UTF-8 byte ordering so the result is independent of dict insertion order.
    """
    delta_genes = set(delta_by_gene)
    seq_genes = set(sequence_by_gene)
    if not delta_genes:
        raise ValueError("delta_by_gene must contain at least one gene")
    missing_seq = delta_genes - seq_genes
    if missing_seq:
        raise KeyError(
            f"{len(missing_seq)} gene(s) lack an ESM sequence vector: {sorted(missing_seq)[:5]} ..."
        )
    missing_delta = seq_genes - delta_genes
    if missing_delta:
        raise KeyError(
            f"{len(missing_delta)} gene(s) lack a delta vector: {sorted(missing_delta)[:5]} ..."
        )
    return sorted(delta_genes, key=lambda g: g.encode("utf-8"))


def _stack(
    by_gene: dict[str, NDArray],
    gene_order: list[str],
    *,
    name: str,
) -> NDArray[np.float64]:
    """Stack per-gene vectors into a ``(n_genes, dim)`` matrix in canonical order.

    Fails closed on ragged (inconsistent-length), non-1-D, empty or non-finite
    feature vectors.
    """
    rows: list[NDArray[np.float64]] = []
    expected_dim: int | None = None
    for gene in gene_order:
        vec = np.asarray(by_gene[gene], dtype=np.float64)
        if vec.ndim != 1:
            raise ValueError(f"{name} vector for {gene!r} must be 1-D, got shape {vec.shape}")
        if vec.size == 0:
            raise ValueError(f"{name} vector for {gene!r} is empty")
        if not np.all(np.isfinite(vec)):
            raise ValueError(f"{name} vector for {gene!r} contains non-finite values")
        if expected_dim is None:
            expected_dim = vec.size
        elif vec.size != expected_dim:
            raise ValueError(
                f"{name} vectors have inconsistent length: {gene!r} has {vec.size}, "
                f"expected {expected_dim}"
            )
        rows.append(vec)
    return np.ascontiguousarray(np.vstack(rows))


def _fit_pca_scores(
    matrix: NDArray[np.float64],
    n_components: int,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Fit a deterministic, sign-oriented PCA.

    Parameters
    ----------
    matrix : numpy.ndarray
        Fit matrix, shape ``(n_genes, dim)``.
    n_components : int
        Number of components to retain.

    Returns
    -------
    scores : numpy.ndarray
        Per-gene PCA scores, shape ``(n_genes, n_components)``, after applying
        the registered sign-orientation policy.
    explained_variance : numpy.ndarray
        Explained variance per component, shape ``(n_components,)``.
    components : numpy.ndarray
        Sign-oriented loadings, shape ``(n_components, dim)``. Each row's
        largest-magnitude loading is positive, removing the SVD sign degeneracy.
    """
    pca = PCA(n_components=n_components, svd_solver="full", random_state=0)
    pca.fit(matrix)
    components = np.ascontiguousarray(pca.components_, dtype=np.float64)
    explained = np.ascontiguousarray(pca.explained_variance_, dtype=np.float64)
    signs = _orientation_signs(components)
    # Apply the sign convention to the basis so the loadings are deterministic
    # and immune to the SVD's arbitrary internal sign degeneracy.
    components = components * signs[:, np.newaxis]
    centered = matrix - pca.mean_
    scores = centered @ components.T
    return (
        np.ascontiguousarray(scores),
        explained,
        np.ascontiguousarray(components),
    )


def _orientation_signs(components: NDArray[np.float64]) -> NDArray[np.float64]:
    """Return per-component signs fixing the largest-magnitude loading positive.

    Each component's sign is chosen so that its largest-magnitude loading is
    positive; ``numpy.argmax`` breaks magnitude ties by the lowest index, making
    the policy fully deterministic.

    Parameters
    ----------
    components : numpy.ndarray
        PCA components, shape ``(n_components, dim)``.

    Returns
    -------
    numpy.ndarray
        Signs in ``{-1.0, +1.0}``, shape ``(n_components,)``.
    """
    signs = np.ones(components.shape[0], dtype=np.float64)
    for i in range(components.shape[0]):
        row = components[i]
        pivot = int(np.argmax(np.abs(row)))
        if row[pivot] < 0:
            signs[i] = -1.0
    return signs


def _round_array(arr: NDArray) -> list:
    """Round-to-12-decimal nested list for stable cross-platform checksums."""
    return np.round(np.asarray(arr, dtype=np.float64), 12).tolist()
