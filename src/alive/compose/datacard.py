"""Validated Norman data-card, composite run identity, and provenance capture.

COMPOSE-K562-v1 Phase 2a, Task 2a-10. Implements spec §10.6 (composite ``run_id``
inputs) and CLAUDE.md §11 (run identity, provenance, immutability) on top of the
shared CARTOGRAPHER provenance spine (:mod:`alive.provenance`).

A *data-card* is a JSON-serialisable dict that binds a processed Norman AnnData to
its declared source, its raw/source digest, its DIRECTLY-derived schema and counts,
and its outcome-independent exclusions. The counts and schema are derived from the
AnnData / parsed labels — caller-supplied counts may be passed only as a *cross
check* and can never silently overwrite a derived value: a contradiction raises
:class:`DataCardError` (CLAUDE.md §5, §7; spec §2.2).

The composite ``run_id`` (spec §10.6) is

    run_id = sha256(config_digest, data_card_digest, raw/source_digest, sequence_mapping_digest)

computed through :func:`alive.provenance.compute_run_id`, so the COMPOSE seal /
run-identity stays permanently independent of TG-K562 (CLAUDE.md §6.3).

Public API
----------
DataCardError
    Raised on a derived/declared count contradiction or an invalid raw/source
    digest declaration.
build_data_card(...)
    Build the validated data-card dict from separate declared source and processed
    assets.
compute_compose_run_id(...)
    Composite COMPOSE ``run_id`` from config + data-card + raw/source + sequence
    mapping digests.
capture_compose_provenance(...)
    Build a :class:`alive.provenance.RunLedger` recording environment, the data-card,
    the processed file, and the device/precision context.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import anndata

from alive.data.norman import parse_labels
from alive.provenance import (
    RunLedger,
    capture_environment,
    compute_run_id,
    sha256_bytes,
    sha256_file,
    sha256_json,
)

#: Cross-check keys a caller may declare; each must equal the derived value.
_COUNT_KEYS = ("n_cells", "n_genes", "n_control", "n_singles", "n_doubles")


class DataCardError(ValueError):
    """Raised when a data-card declaration is invalid or self-contradictory.

    Covers (a) a caller-supplied count that contradicts the value derived from the
    AnnData / parsed labels, and (b) an invalid raw-vs-source digest declaration
    (neither or both of ``raw_asset`` / ``declared_source_digest`` supplied), and
    (c) an invalid composite-run-id call (neither or both of ``data_card`` /
    ``data_card_digest`` supplied).

    Parameters
    ----------
    message : str
        Human-readable description of the violation.
    """


def _derive_counts(
    adata: anndata.AnnData,
    *,
    perturbation_col: str,
    control_token: str,
    combo_sep: str,
) -> dict[str, int]:
    """Derive cell/gene/control/single/double counts directly from the AnnData.

    Parameters
    ----------
    adata : anndata.AnnData
        Processed Norman AnnData (read backed for large files).
    perturbation_col : str
        Name of the ``obs`` column holding the perturbation label per cell.
    control_token : str
        Label value marking a control cell.
    combo_sep : str
        Separator joining the two genes of a combinatorial (double) perturbation.

    Returns
    -------
    dict of str to int
        ``{"n_cells", "n_genes", "n_control", "n_singles", "n_doubles"}``.

    Raises
    ------
    DataCardError
        If ``perturbation_col`` is absent from ``adata.obs``.
    """
    if perturbation_col not in adata.obs.columns:
        raise DataCardError(
            f"perturbation column {perturbation_col!r} not found in obs; "
            f"available columns: {sorted(adata.obs.columns)}"
        )
    labels = adata.obs[perturbation_col].to_numpy()
    singles, doubles, control = parse_labels(
        labels, control_token=control_token, combo_sep=combo_sep
    )
    return {
        "n_cells": int(adata.n_obs),
        "n_genes": int(adata.n_vars),
        "n_control": int(control.size),
        "n_singles": int(len(singles)),
        "n_doubles": int(len(doubles)),
    }


def _check_declared_counts(derived: Mapping[str, int], declared: Mapping[str, int]) -> None:
    """Validate that declared counts match the derived (authoritative) values.

    Parameters
    ----------
    derived : Mapping of str to int
        The counts derived directly from the data (authoritative).
    declared : Mapping of str to int
        Caller-supplied counts, used as a cross check only.

    Raises
    ------
    DataCardError
        If a declared key is unknown, or any declared value differs from the
        derived value. The derived value always wins; declarations never
        overwrite it.
    """
    for key, value in declared.items():
        if key not in _COUNT_KEYS:
            raise DataCardError(f"unknown declared count {key!r}; expected one of {_COUNT_KEYS}")
        if int(value) != derived[key]:
            raise DataCardError(
                f"declared {key}={value} contradicts derived {key}={derived[key]}; "
                "derived counts are authoritative and cannot be overwritten"
            )


def _derive_schema(adata: anndata.AnnData) -> dict[str, list[str]]:
    """Derive the obs/var column schema directly from the AnnData.

    Parameters
    ----------
    adata : anndata.AnnData
        The processed AnnData.

    Returns
    -------
    dict of str to list of str
        ``{"obs_columns", "var_columns"}`` each a sorted list for determinism.
    """
    return {
        "obs_columns": sorted(str(c) for c in adata.obs.columns),
        "var_columns": sorted(str(c) for c in adata.var.columns),
    }


def _resolve_raw_or_source(
    raw_asset: str | Path | None,
    declared_source_digest: str | None,
) -> dict[str, str]:
    """Resolve the raw-vs-source digest branch (spec §10.6).

    Exactly one of ``raw_asset`` / ``declared_source_digest`` must be supplied: the
    raw asset's SHA-256 when a raw asset exists, otherwise a declared immutable
    source digest.

    Parameters
    ----------
    raw_asset : str or Path or None
        Path to the raw downloaded asset, if one exists locally.
    declared_source_digest : str or None
        An immutable digest of the source (e.g. a GEO accession content digest)
        used when no raw asset is held locally.

    Returns
    -------
    dict of str to str
        ``{"kind": "raw_sha256" | "declared_source_digest", "digest": <hex>}``.

    Raises
    ------
    DataCardError
        If neither or both inputs are supplied.
    """
    if raw_asset is not None and declared_source_digest is not None:
        raise DataCardError("supply exactly one of raw_asset or declared_source_digest, not both")
    if raw_asset is not None:
        return {"kind": "raw_sha256", "digest": sha256_file(raw_asset)}
    if declared_source_digest is not None:
        return {"kind": "declared_source_digest", "digest": str(declared_source_digest)}
    raise DataCardError(
        "no raw asset present: a declared_source_digest is required so the "
        "data-card binds an immutable source identity"
    )


def build_data_card(
    *,
    processed_h5ad: str | Path,
    source_uri: str,
    source_doi: str,
    license: str,
    cell_line: str,
    modality: str,
    processing_version: str,
    perturbation_col: str,
    control_token: str,
    combo_sep: str,
    raw_asset: str | Path | None = None,
    declared_source_digest: str | None = None,
    declared_counts: Mapping[str, int] | None = None,
    exclusions: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a validated Norman data-card from separate source and processed assets.

    Schema and counts are derived DIRECTLY from the processed AnnData / parsed
    labels. Any ``declared_counts`` are treated as a cross check only: a mismatch
    raises and the derived values always win (CLAUDE.md §5, §7). The processed
    AnnData is opened in backed read mode so this is safe on large files.

    Parameters
    ----------
    processed_h5ad : str or Path
        Path to the processed Norman ``.h5ad``. Its SHA-256 is recorded and its
        obs/var schema and counts are derived from it.
    source_uri : str
        Canonical source URI (e.g. the GEO accession URL).
    source_doi : str
        DOI of the source publication.
    license : str
        Data license identifier (e.g. ``"CC-BY-4.0"``).
    cell_line : str
        Cell line of origin (e.g. ``"K562"``).
    modality : str
        Assay modality (e.g. ``"CRISPRa-Perturb-seq"``).
    processing_version : str
        Version tag of the processing pipeline that produced ``processed_h5ad``.
    perturbation_col : str
        Name of the ``obs`` perturbation-label column.
    control_token : str
        Label value marking a control cell.
    combo_sep : str
        Separator joining the two genes of a double perturbation.
    raw_asset : str or Path or None, optional
        Path to the raw downloaded asset. If present, its SHA-256 is the
        raw/source digest; otherwise ``declared_source_digest`` is required.
    declared_source_digest : str or None, optional
        Immutable source digest used when no raw asset is held locally. Mutually
        exclusive with ``raw_asset``.
    declared_counts : Mapping of str to int or None, optional
        Cross-check counts. Each must equal the derived value or a
        :class:`DataCardError` is raised. Never overwrites derived values.
    exclusions : Sequence of Mapping or None, optional
        Outcome-independent exclusion records (cells/genes removed for QC or
        feature-availability reasons, never for response strength). Recorded
        verbatim and hashed into ``exclusions_manifest_sha256``.

    Returns
    -------
    dict
        The validated, JSON-serialisable data-card.

    Raises
    ------
    DataCardError
        On a declared/derived count contradiction or an invalid raw/source digest
        declaration.
    """
    processed_path = Path(processed_h5ad)
    raw_or_source = _resolve_raw_or_source(raw_asset, declared_source_digest)

    adata = anndata.read_h5ad(processed_path, backed="r")
    try:
        counts = _derive_counts(
            adata,
            perturbation_col=perturbation_col,
            control_token=control_token,
            combo_sep=combo_sep,
        )
        schema = _derive_schema(adata)
    finally:
        if adata.isbacked and adata.file is not None:
            adata.file.close()

    if declared_counts is not None:
        _check_declared_counts(counts, declared_counts)

    exclusion_list = [dict(e) for e in (exclusions or [])]

    return {
        "source": {"uri": source_uri, "doi": source_doi},
        "license": license,
        "cell_line": cell_line,
        "modality": modality,
        "processing_version": processing_version,
        "processed_sha256": sha256_file(processed_path),
        "raw_or_source": raw_or_source,
        "schema": schema,
        "counts": counts,
        "exclusions": exclusion_list,
        "exclusions_manifest_sha256": sha256_json(exclusion_list),
    }


def compute_compose_run_id(
    *,
    config_digest: str,
    raw_or_source_digest: str,
    sequence_mapping_digest: str,
    data_card: Mapping[str, Any] | None = None,
    data_card_digest: str | None = None,
    length: int = 16,
) -> str:
    """Composite COMPOSE ``run_id`` (spec §10.6) over config + data-card + raw + seq.

    Binds the resolved config to the canonical data-card digest, the raw/source
    digest, and the sequence-mapping digest, so the same config on different data
    yields a different ``run_id`` and the COMPOSE seal stays independent of
    TG-K562 (CLAUDE.md §6.3). Delegates to :func:`alive.provenance.compute_run_id`.

    Exactly one of ``data_card`` (canonicalised here) or ``data_card_digest``
    (precomputed) must be supplied.

    Parameters
    ----------
    config_digest : str
        Deterministic digest of the resolved config.
    raw_or_source_digest : str
        The raw-or-source digest (``data_card["raw_or_source"]["digest"]``).
    sequence_mapping_digest : str
        Canonical digest of the gene→protein-sequence mapping.
    data_card : Mapping or None, optional
        The data-card dict; its canonical-JSON SHA-256 is used as the data-card
        digest. Mutually exclusive with ``data_card_digest``.
    data_card_digest : str or None, optional
        Precomputed canonical data-card digest. Mutually exclusive with
        ``data_card``.
    length : int, optional
        Number of leading hex characters to return. Defaults to 16.

    Returns
    -------
    str
        ``length``-character lowercase hexadecimal run identifier.

    Raises
    ------
    DataCardError
        If neither or both of ``data_card`` / ``data_card_digest`` are supplied.
    """
    if (data_card is None) == (data_card_digest is None):
        raise DataCardError("supply exactly one of data_card or data_card_digest")
    digest = data_card_digest if data_card_digest is not None else sha256_json(data_card)
    return compute_run_id(
        config_digest,
        digest,
        raw_or_source_digest,
        sequence_mapping_digest,
        length=length,
    )


def capture_compose_provenance(
    *,
    run_id: str,
    config_digest: str,
    data_card: Mapping[str, Any],
    processed_h5ad: str | Path,
    sequence_mapping_digest: str,
    registered_seeds: Sequence[int],
    lockfile_path: str | Path,
    device: str,
    precision: str,
    repo_dir: str | Path | None = None,
) -> RunLedger:
    """Build a :class:`RunLedger` capturing the COMPOSE run's provenance (§11).

    Captures the Python/platform versions, the git HEAD SHA, the dependency-lock
    hash, and the registered seeds via :func:`alive.provenance.capture_environment`,
    then records the data-card, the processed AnnData, the sequence-mapping digest,
    and the device/precision context as immutable, write-once ledger artifacts.

    Parameters
    ----------
    run_id : str
        Composite run identifier from :func:`compute_compose_run_id`.
    config_digest : str
        Deterministic digest of the resolved config (recorded as the ledger's
        ``config_sha256``).
    data_card : Mapping
        The validated data-card dict; its canonical-JSON SHA-256 is recorded.
    processed_h5ad : str or Path
        Path to the processed AnnData; stream-hashed and recorded.
    sequence_mapping_digest : str
        Canonical digest of the gene→protein-sequence mapping; recorded.
    registered_seeds : Sequence of int
        Registered random seeds for reproducibility.
    lockfile_path : str or Path
        Path to the dependency lockfile (e.g. ``uv.lock``); its SHA-256 is captured.
    device : str
        Compute device tag (e.g. ``"cpu"``, ``"cuda"``).
    precision : str
        Numerical precision tag (e.g. ``"float32"``, ``"bf16"``).
    repo_dir : str or Path or None, optional
        Working directory for the git-HEAD lookup. ``None`` uses the current
        working directory; a non-repo path yields the ``"UNKNOWN"`` sentinel.

    Returns
    -------
    RunLedger
        A write-once ledger recording the full COMPOSE provenance set.
    """
    env = capture_environment(lockfile_path, registered_seeds, repo_dir=repo_dir)
    ledger = RunLedger(run_id=run_id, config_sha256=config_digest, environment=env)
    ledger.record_artifact("data_card", sha256_json(data_card))
    ledger.record_file("processed_h5ad", processed_h5ad)
    ledger.record_artifact("sequence_mapping", sequence_mapping_digest)
    ledger.record_artifact(
        "device_precision",
        sha256_bytes(f"{device}|{precision}".encode("utf-8")),
    )
    return ledger
