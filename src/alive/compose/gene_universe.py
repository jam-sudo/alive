"""Outcome-free, exact-size GEARS gene-roster construction.

The scientific COMPOSE response universe remains the full measured gene order
(``U_full``).  This module creates only the method-specific GEARS roster
(``R_gears``) and the preprocessing transform that normalizes allowed fit rows on
``U_full`` *before* selecting ``R_gears``.  It imports no outcome-store surface.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

import numpy as np
from scipy import sparse

from alive.compose.fit_role import canonical_gene_order_sha256
from alive.compose.response import rank_gene_indices_by_variance
from alive.io import atomic_write_once
from alive.provenance import sha256_bytes, sha256_json

_BARE_SHA256 = re.compile(r"[0-9a-f]{64}")
_ALIAS_SCHEMA = "compose_gene_aliases_v1"
_REPORT_SCHEMA = "compose_gears_mandatory_report_v1"
_ROSTER_SCHEMA = "compose_gears_gene_roster_v1"
_VARIANCE_BLOCK_SIZE = 512


class GeneUniverseError(ValueError):
    """Raised when a GEARS roster or one of its identities is invalid."""


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _BARE_SHA256.fullmatch(value) is None:
        raise GeneUniverseError(f"{field} must be a bare lowercase SHA-256")
    return value


def _canonical_json_text(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _read_stable_regular_bytes(path: str | Path, *, label: str) -> bytes:
    """Read one non-symlink regular file through a stable descriptor."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(Path(path), flags)
    except OSError as exc:
        raise GeneUniverseError(f"cannot open {label} safely: {exc}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise GeneUniverseError(f"{label} is not a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
        before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        data = b"".join(chunks)
        if before_identity != after_identity or len(data) != before.st_size:
            raise GeneUniverseError(f"{label} bytes changed while being read")
        return data
    finally:
        os.close(fd)


def _validated_gene_order(values: Sequence[str], *, field: str) -> tuple[str, ...]:
    genes = tuple(values)
    if not genes or any(not isinstance(gene, str) or not gene for gene in genes):
        raise GeneUniverseError(f"{field} must contain non-empty string gene IDs")
    if len(set(genes)) != len(genes):
        raise GeneUniverseError(f"{field} must contain unique gene IDs")
    return genes


@dataclass(frozen=True)
class AliasRecord:
    """One registered legacy-to-canonical gene-symbol mapping."""

    raw_symbol: str
    canonical_symbol: str
    source: str
    version: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "canonical_symbol": self.canonical_symbol,
            "raw_symbol": self.raw_symbol,
            "reason": self.reason,
            "source": self.source,
            "version": self.version,
        }


@dataclass(frozen=True)
class AliasMap:
    """Digest-bound alias registry applied before full artifacts are frozen."""

    records: tuple[AliasRecord, ...]
    artifact_sha256: str

    @classmethod
    def load(cls, path: str | Path, *, expected_sha256: str) -> AliasMap:
        """Load and byte-verify an exact alias artifact."""
        expected = _require_sha256(expected_sha256, field="expected_sha256")
        data = _read_stable_regular_bytes(path, label="alias artifact")
        observed = sha256_bytes(data)
        if observed != expected:
            raise GeneUniverseError("alias artifact SHA-256 mismatch")
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise GeneUniverseError(f"cannot read alias artifact: {exc}") from exc
        if not isinstance(payload, dict) or set(payload) != {"aliases", "schema"}:
            raise GeneUniverseError("alias artifact has an unexpected key set")
        if payload["schema"] != _ALIAS_SCHEMA or not isinstance(payload["aliases"], list):
            raise GeneUniverseError("alias artifact schema is invalid")

        records: list[AliasRecord] = []
        for raw in payload["aliases"]:
            keys = {"canonical_symbol", "raw_symbol", "reason", "source", "version"}
            if not isinstance(raw, dict) or set(raw) != keys:
                raise GeneUniverseError("alias record has an unexpected key set")
            if not all(isinstance(raw[key], str) and raw[key] for key in keys):
                raise GeneUniverseError("alias fields must be non-empty strings")
            records.append(AliasRecord(**raw))

        records.sort(key=lambda record: record.raw_symbol.encode("utf-8"))
        raw_symbols = [record.raw_symbol for record in records]
        if len(set(raw_symbols)) != len(raw_symbols):
            raise GeneUniverseError("alias artifact contains duplicate raw symbols")
        canonical_symbols = [record.canonical_symbol for record in records]
        if set(raw_symbols) & set(canonical_symbols):
            raise GeneUniverseError("alias chains/cycles are forbidden")
        for record in records:
            if record.raw_symbol == record.canonical_symbol:
                raise GeneUniverseError("identity aliases are forbidden")
        return cls(records=tuple(records), artifact_sha256=observed)

    def canonicalize(self, symbol: str) -> str:
        """Return the registered canonical spelling for ``symbol``."""
        value = str(symbol)
        if not value:
            raise GeneUniverseError("gene symbol must be non-empty")
        mapping = {record.raw_symbol: record.canonical_symbol for record in self.records}
        return mapping.get(value, value)


@dataclass(frozen=True)
class EligibilityExclusion:
    """Machine-readable reason a perturbation candidate is not GEARS-composable."""

    token: str
    gene: str
    canonical_gene: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "canonical_gene": self.canonical_gene,
            "gene": self.gene,
            "reason": self.reason,
            "token": self.token,
        }


@dataclass(frozen=True)
class MandatoryReport:
    """Outcome-free report produced before an owner chooses ``N_target``."""

    full_var: tuple[str, ...]
    response_hvg_ids: tuple[str, ...]
    eligible_perturbation_genes: tuple[str, ...]
    mandatory_genes: tuple[str, ...]
    eligible_tokens: tuple[str, ...]
    eligibility_exclusions: tuple[EligibilityExclusion, ...]
    n_candidates: int
    n_eligible: int
    n_excluded: int
    response_hvg_perturbation_overlap: int
    fit_artifact_content_sha256: str
    raw_data_sha256: str
    full_var_order_sha256: str
    response_artifact_sha256: str
    response_hvg_sha256: str
    eligibility_sha256: str
    alias_sha256: str
    gene2go_sha256: str
    perturbation_candidate_sha256: str
    median_library: float

    @property
    def mandatory_size(self) -> int:
        return len(self.mandatory_genes)

    def to_dict(self) -> dict[str, object]:
        return {
            "alias_sha256": self.alias_sha256,
            "eligibility_exclusions": [item.to_dict() for item in self.eligibility_exclusions],
            "eligibility_sha256": self.eligibility_sha256,
            "eligible_perturbation_genes": list(self.eligible_perturbation_genes),
            "eligible_tokens": list(self.eligible_tokens),
            "fit_artifact_content_sha256": self.fit_artifact_content_sha256,
            "full_var": list(self.full_var),
            "full_var_order_sha256": self.full_var_order_sha256,
            "gene2go_sha256": self.gene2go_sha256,
            "mandatory_genes": list(self.mandatory_genes),
            "mandatory_size": self.mandatory_size,
            "median_library": self.median_library,
            "n_candidates": self.n_candidates,
            "n_eligible": self.n_eligible,
            "n_excluded": self.n_excluded,
            "perturbation_candidate_sha256": self.perturbation_candidate_sha256,
            "raw_data_sha256": self.raw_data_sha256,
            "response_artifact_sha256": self.response_artifact_sha256,
            "response_hvg_ids": list(self.response_hvg_ids),
            "response_hvg_perturbation_overlap": self.response_hvg_perturbation_overlap,
            "response_hvg_sha256": self.response_hvg_sha256,
            "schema": _REPORT_SCHEMA,
        }


def _parse_candidate(token: str, *, combo_sep: str) -> tuple[str, ...]:
    if not isinstance(token, str) or not token:
        raise GeneUniverseError("perturbation candidates must be non-empty strings")
    parts = tuple(token.split(combo_sep))
    if len(parts) not in {1, 2} or any(not part for part in parts):
        raise GeneUniverseError(f"invalid perturbation candidate token: {token!r}")
    return parts


def compute_mandatory_report(
    *,
    full_var: Sequence[str],
    fit_artifact_identity: Mapping[str, object],
    response_projection: Mapping[str, object],
    perturbation_candidates: Sequence[str],
    gene2go: Iterable[str],
    gene2go_sha256: str,
    alias: AliasMap,
    perturbation_candidate_source_sha256: str | None = None,
    combo_sep: str = "_",
    control_token: str = "control",
) -> MandatoryReport:
    """Compute frozen response-HVG and global perturbation mandatory genes."""
    genes = _validated_gene_order(full_var, field="full_var")
    if not combo_sep or combo_sep == control_token:
        raise GeneUniverseError("combo_sep/control_token contract is invalid")
    full_sha = canonical_gene_order_sha256(genes)
    required_fit = {"content_manifest_sha256", "gene_order_sha256", "raw_data_sha256"}
    if not isinstance(fit_artifact_identity, Mapping) or not required_fit <= set(
        fit_artifact_identity
    ):
        raise GeneUniverseError("fit artifact identity is incomplete")
    fit_content_sha = _require_sha256(
        fit_artifact_identity["content_manifest_sha256"], field="content_manifest_sha256"
    )
    if fit_artifact_identity["gene_order_sha256"] != full_sha:
        raise GeneUniverseError("fit artifact gene order does not match full_var")
    raw_data_sha = str(fit_artifact_identity["raw_data_sha256"])
    if not raw_data_sha:
        raise GeneUniverseError("fit artifact raw_data_sha256 must be non-empty")

    # Every measured column must already be canonical. This also fail-closes the §9
    # "two measured columns collapse to one canonical symbol" case: any such collapse
    # requires a non-canonical column, which this loop rejects first (a separate
    # collapse guard afterward would be unreachable, since `genes` is already unique).
    for gene in genes:
        if alias.canonicalize(gene) != gene:
            raise GeneUniverseError(
                f"full_var contains non-canonical alias {gene!r}; "
                "canonicalize before freezing artifacts"
            )

    response_gene_sha = response_projection.get("gene_order_sha256")
    if response_gene_sha != full_sha:
        raise GeneUniverseError("response projection gene order does not match full_var")
    if response_projection.get("raw_data_sha256") != raw_data_sha:
        raise GeneUniverseError("response projection raw-data identity does not match fit artifact")
    response_sha = _require_sha256(
        response_projection.get("response_artifact_sha256"), field="response_artifact_sha256"
    )
    raw_hvg = response_projection.get("hvg_gene_ids")
    if not isinstance(raw_hvg, list):
        raise GeneUniverseError("response projection hvg_gene_ids must be a list")
    hvg = _validated_gene_order(raw_hvg, field="response hvg_gene_ids")
    full_index = {gene: index for index, gene in enumerate(genes)}
    if any(gene not in full_index for gene in hvg):
        raise GeneUniverseError("response projection contains an HVG outside full_var")
    if tuple(sorted(hvg, key=full_index.__getitem__)) != hvg:
        raise GeneUniverseError("response HVGs are not in canonical full_var order")
    median_library = response_projection.get("median_library")
    if (
        isinstance(median_library, bool)
        or not isinstance(median_library, (int, float))
        or not np.isfinite(median_library)
        or median_library <= 0
    ):
        raise GeneUniverseError("response median_library must be finite and positive")

    go_sha = _require_sha256(gene2go_sha256, field="gene2go_sha256")
    go_values = tuple(gene2go)
    if not go_values or any(not isinstance(gene, str) or not gene for gene in go_values):
        raise GeneUniverseError("gene2go must contain non-empty string gene IDs")
    if len(set(go_values)) != len(go_values):
        raise GeneUniverseError("gene2go gene roster must be unique")
    go_genes = set(go_values)
    canonical_go = {alias.canonicalize(gene) for gene in go_genes}
    if not all(isinstance(token, str) and token for token in perturbation_candidates):
        raise GeneUniverseError("perturbation candidates must be non-empty strings")
    candidates = sorted(set(perturbation_candidates), key=lambda value: value.encode("utf-8"))
    if len(candidates) != len(perturbation_candidates):
        raise GeneUniverseError("perturbation candidate list must be unique")
    candidate_sha = (
        _require_sha256(
            perturbation_candidate_source_sha256,
            field="perturbation_candidate_source_sha256",
        )
        if perturbation_candidate_source_sha256 is not None
        else sha256_json(candidates)
    )

    eligible_tokens: list[str] = []
    perturbation_genes: set[str] = set()
    exclusions: list[EligibilityExclusion] = []
    canonical_candidates: dict[tuple[str, ...], str] = {}
    for token in candidates:
        if token == control_token:
            continue
        parts = _parse_candidate(token, combo_sep=combo_sep)
        if control_token in parts:
            raise GeneUniverseError(f"control token cannot be a perturbation component: {token!r}")
        if len(parts) == 2 and parts[0] == parts[1]:
            raise GeneUniverseError(f"self-combo perturbation is invalid: {token!r}")
        canonical_parts = tuple(alias.canonicalize(part) for part in parts)
        if len(canonical_parts) == 2 and canonical_parts[0] == canonical_parts[1]:
            raise GeneUniverseError(
                f"perturbation candidate {token!r} collapses to a canonical self-combo"
            )
        canonical_key = (
            tuple(sorted(canonical_parts, key=lambda value: value.encode("utf-8")))
            if len(canonical_parts) == 2
            else canonical_parts
        )
        previous = canonical_candidates.setdefault(canonical_key, token)
        if previous != token:
            raise GeneUniverseError(
                f"perturbation candidates {previous!r} and {token!r} "
                "collapse to one canonical target"
            )
        token_exclusions: list[EligibilityExclusion] = []
        for raw_gene, canonical_gene in zip(parts, canonical_parts, strict=True):
            if canonical_gene not in full_index:
                reason = "absent_from_full_var"
            elif canonical_gene not in canonical_go:
                reason = "absent_from_gene2go"
            else:
                continue
            token_exclusions.append(
                EligibilityExclusion(
                    token=token,
                    gene=raw_gene,
                    canonical_gene=canonical_gene,
                    reason=reason,
                )
            )
        if token_exclusions:
            exclusions.extend(token_exclusions)
        else:
            eligible_tokens.append(token)
            perturbation_genes.update(canonical_parts)

    eligible_genes = tuple(sorted(perturbation_genes, key=full_index.__getitem__))
    mandatory_set = set(hvg) | perturbation_genes
    mandatory = tuple(gene for gene in genes if gene in mandatory_set)
    exclusions.sort(
        key=lambda item: (
            item.token.encode("utf-8"),
            item.canonical_gene.encode("utf-8"),
            item.reason,
        )
    )
    eligibility_payload = {
        "eligible_perturbation_genes": list(eligible_genes),
        "eligible_tokens": eligible_tokens,
        "exclusions": [item.to_dict() for item in exclusions],
    }
    noncontrol_count = sum(token != control_token for token in candidates)
    return MandatoryReport(
        full_var=genes,
        response_hvg_ids=hvg,
        eligible_perturbation_genes=eligible_genes,
        mandatory_genes=mandatory,
        eligible_tokens=tuple(eligible_tokens),
        eligibility_exclusions=tuple(exclusions),
        n_candidates=noncontrol_count,
        n_eligible=len(eligible_tokens),
        n_excluded=noncontrol_count - len(eligible_tokens),
        response_hvg_perturbation_overlap=len(set(hvg) & perturbation_genes),
        fit_artifact_content_sha256=fit_content_sha,
        raw_data_sha256=raw_data_sha,
        full_var_order_sha256=full_sha,
        response_artifact_sha256=response_sha,
        response_hvg_sha256=sha256_json(list(hvg)),
        eligibility_sha256=sha256_json(eligibility_payload),
        alias_sha256=alias.artifact_sha256,
        gene2go_sha256=go_sha,
        perturbation_candidate_sha256=candidate_sha,
        median_library=float(median_library),
    )


def _control_variance(counts: sparse.spmatrix | np.ndarray, *, median_library: float) -> np.ndarray:
    if sparse.issparse(counts):
        matrix = sparse.csr_matrix(counts, dtype=np.float64, copy=True)
        if matrix.data.size and (
            not np.all(np.isfinite(matrix.data))
            or np.any(matrix.data < 0)
            or np.any(matrix.data != np.floor(matrix.data))
        ):
            raise GeneUniverseError("control_counts_full must contain raw non-negative integers")
        library = np.asarray(matrix.sum(axis=1)).ravel()
        scale = np.divide(
            median_library,
            library,
            out=np.zeros_like(library, dtype=np.float64),
            where=library > 0,
        )
        normalized = matrix.multiply(scale[:, None]).tocsr()
        normalized.data = np.log1p(normalized.data)
        # Match response._select_hvg's numpy ``var(axis=0)`` arithmetic exactly
        # without densifying the whole control matrix. Variance is column-local,
        # so bounded column blocks are identical to one full dense call.
        variance = np.empty(normalized.shape[1], dtype=np.float64)
        for start in range(0, normalized.shape[1], _VARIANCE_BLOCK_SIZE):
            stop = min(start + _VARIANCE_BLOCK_SIZE, normalized.shape[1])
            variance[start:stop] = normalized[:, start:stop].toarray().var(axis=0)
        return variance

    matrix = np.asarray(counts, dtype=np.float64)
    if (
        matrix.ndim != 2
        or not np.all(np.isfinite(matrix))
        or np.any(matrix < 0)
        or np.any(matrix != np.floor(matrix))
    ):
        raise GeneUniverseError("control_counts_full must be a 2-D raw-count matrix")
    library = matrix.sum(axis=1, keepdims=True)
    safe = np.where(library > 0, library, 1.0)
    normalized = np.log1p(matrix * (median_library / safe))
    return normalized.var(axis=0)


@dataclass(frozen=True)
class GearsGeneRosterArtifact:
    """Immutable exact-size, method-specific GEARS roster."""

    ordered_roster: tuple[str, ...]
    n_target: int
    mandatory_genes: tuple[str, ...]
    response_hvg_ids: tuple[str, ...]
    eligible_perturbation_genes: tuple[str, ...]
    eligibility_exclusions: tuple[EligibilityExclusion, ...]
    fill_count: int
    provenance: Mapping[str, object]
    normalization_basis: Mapping[str, object]
    ordered_roster_sha256: str
    artifact_checksum: str

    @property
    def mandatory_size(self) -> int:
        return len(self.mandatory_genes)

    def _core_dict(self) -> dict[str, object]:
        return {
            "eligibility_exclusions": [item.to_dict() for item in self.eligibility_exclusions],
            "eligible_perturbation_genes": list(self.eligible_perturbation_genes),
            "fill_count": self.fill_count,
            "mandatory_genes": list(self.mandatory_genes),
            "mandatory_size": self.mandatory_size,
            "n_target": self.n_target,
            "normalization_basis": dict(self.normalization_basis),
            "ordered_roster": list(self.ordered_roster),
            "ordered_roster_sha256": self.ordered_roster_sha256,
            "provenance": dict(self.provenance),
            "response_hvg_ids": list(self.response_hvg_ids),
            "schema": _ROSTER_SCHEMA,
        }

    def to_dict(self) -> dict[str, object]:
        payload = self._core_dict()
        payload["artifact_checksum"] = self.artifact_checksum
        return payload

    def write(self, path: str | Path) -> None:
        """Publish canonical JSON once; allow only a byte-identical repeat."""
        destination = Path(path)
        text = _canonical_json_text(self.to_dict())
        if destination.exists() or destination.is_symlink():
            if destination.is_file() and not destination.is_symlink():
                try:
                    if destination.read_text(encoding="utf-8") == text:
                        return
                except (OSError, UnicodeError):
                    pass
            raise GeneUniverseError("GEARS roster destination already exists with different bytes")
        atomic_write_once(destination, text)


def generate_gears_gene_roster(
    *,
    mandatory_report: MandatoryReport,
    control_counts_full: sparse.spmatrix | np.ndarray,
    control_row_identity_sha256: str,
    generator_code_sha256: str,
    n_target: int,
    out_path: str | Path | None = None,
) -> GearsGeneRosterArtifact:
    """Fill an exact-size GEARS roster by full-universe control variance."""
    if isinstance(n_target, bool) or not isinstance(n_target, int) or n_target < 1:
        raise GeneUniverseError("n_target must be a positive integer")
    if mandatory_report.mandatory_size > n_target:
        raise GeneUniverseError("mandatory gene set exceeds n_target")
    if n_target > len(mandatory_report.full_var):
        raise GeneUniverseError("n_target exceeds the full measured universe")
    control_sha = _require_sha256(control_row_identity_sha256, field="control_row_identity_sha256")
    code_sha = _require_sha256(generator_code_sha256, field="generator_code_sha256")
    shape = getattr(control_counts_full, "shape", ())
    if len(shape) != 2 or shape[0] < 1 or shape[1] != len(mandatory_report.full_var):
        raise GeneUniverseError("control_counts_full shape does not match full_var")

    variance = _control_variance(
        control_counts_full, median_library=mandatory_report.median_library
    )
    full_index = {gene: index for index, gene in enumerate(mandatory_report.full_var)}
    mandatory = set(mandatory_report.mandatory_genes)
    candidate_indices = [
        full_index[gene] for gene in mandatory_report.full_var if gene not in mandatory
    ]
    ranked_indices = rank_gene_indices_by_variance(variance, candidate_indices)
    ranked = [mandatory_report.full_var[int(index)] for index in ranked_indices]
    fill_count = n_target - len(mandatory)
    selected = mandatory | set(ranked[:fill_count])
    ordered = tuple(gene for gene in mandatory_report.full_var if gene in selected)
    if len(ordered) != n_target or len(set(ordered)) != n_target:
        raise GeneUniverseError("internal exact-size roster construction failure")
    if not set(mandatory_report.response_hvg_ids) <= set(ordered):
        raise GeneUniverseError("GEARS roster omitted a frozen response HVG")

    normalization_basis = {
        "gene_order": "U_full",
        "median_library": mandatory_report.median_library,
        "subset_after_normalize": True,
        "transform": ["normalize_total_median", "log1p"],
    }
    provenance = {
        "alias_sha256": mandatory_report.alias_sha256,
        "control_row_identity_sha256": control_sha,
        "eligibility_sha256": mandatory_report.eligibility_sha256,
        "fit_artifact_content_sha256": mandatory_report.fit_artifact_content_sha256,
        "full_var_order_sha256": mandatory_report.full_var_order_sha256,
        "gene2go_sha256": mandatory_report.gene2go_sha256,
        "generator_code_sha256": code_sha,
        "n_target": n_target,
        "perturbation_candidate_sha256": mandatory_report.perturbation_candidate_sha256,
        "raw_data_sha256": mandatory_report.raw_data_sha256,
        "response_artifact_sha256": mandatory_report.response_artifact_sha256,
        "response_hvg_sha256": mandatory_report.response_hvg_sha256,
    }
    roster_sha = sha256_json(list(ordered))
    provisional = GearsGeneRosterArtifact(
        ordered_roster=ordered,
        n_target=n_target,
        mandatory_genes=mandatory_report.mandatory_genes,
        response_hvg_ids=mandatory_report.response_hvg_ids,
        eligible_perturbation_genes=mandatory_report.eligible_perturbation_genes,
        eligibility_exclusions=mandatory_report.eligibility_exclusions,
        fill_count=fill_count,
        provenance=MappingProxyType(provenance),
        normalization_basis=MappingProxyType(normalization_basis),
        ordered_roster_sha256=roster_sha,
        artifact_checksum="",
    )
    artifact = GearsGeneRosterArtifact(
        **{
            **provisional.__dict__,
            "artifact_checksum": sha256_json(provisional._core_dict()),
        }
    )
    if out_path is not None:
        artifact.write(out_path)
    return artifact


def load_gears_gene_roster(
    path: str | Path, *, expected_file_sha256: str
) -> GearsGeneRosterArtifact:
    """Load and fully validate a canonical GEARS roster artifact."""
    data = _read_stable_regular_bytes(path, label="GEARS roster artifact")
    expected = _require_sha256(expected_file_sha256, field="expected_file_sha256")
    if sha256_bytes(data) != expected:
        raise GeneUniverseError("GEARS roster file SHA-256 mismatch")
    try:
        text = data.decode("utf-8")
        payload = json.loads(text)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GeneUniverseError(f"cannot read GEARS roster: {exc}") from exc
    expected_keys = {
        "artifact_checksum",
        "eligibility_exclusions",
        "eligible_perturbation_genes",
        "fill_count",
        "mandatory_genes",
        "mandatory_size",
        "n_target",
        "normalization_basis",
        "ordered_roster",
        "ordered_roster_sha256",
        "provenance",
        "response_hvg_ids",
        "schema",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise GeneUniverseError("GEARS roster artifact has an unexpected key set")
    if payload["schema"] != _ROSTER_SCHEMA:
        raise GeneUniverseError("GEARS roster artifact schema is invalid")
    declared = _require_sha256(payload["artifact_checksum"], field="artifact_checksum")
    core = dict(payload)
    del core["artifact_checksum"]
    if sha256_json(core) != declared:
        raise GeneUniverseError("GEARS roster artifact checksum mismatch")
    if text != _canonical_json_text(payload):
        raise GeneUniverseError("GEARS roster artifact is not canonical JSON")
    for field in (
        "ordered_roster",
        "mandatory_genes",
        "response_hvg_ids",
        "eligible_perturbation_genes",
        "eligibility_exclusions",
    ):
        if not isinstance(payload[field], list):
            raise GeneUniverseError(f"GEARS roster {field} must be a list")
    ordered = _validated_gene_order(payload["ordered_roster"], field="ordered_roster")
    mandatory = _validated_gene_order(payload["mandatory_genes"], field="mandatory_genes")
    hvg = _validated_gene_order(payload["response_hvg_ids"], field="response_hvg_ids")
    eligible = tuple(payload["eligible_perturbation_genes"])
    if any(not isinstance(gene, str) or not gene for gene in eligible) or len(set(eligible)) != len(
        eligible
    ):
        raise GeneUniverseError("eligible_perturbation_genes are invalid")
    try:
        exclusions = tuple(
            EligibilityExclusion(**item) for item in payload["eligibility_exclusions"]
        )
    except (TypeError, AttributeError) as exc:
        raise GeneUniverseError("GEARS roster exclusions are malformed") from exc
    valid_exclusion_reasons = {"absent_from_full_var", "absent_from_gene2go"}
    if any(
        not all(
            isinstance(value, str) and value
            for value in (item.token, item.gene, item.canonical_gene, item.reason)
        )
        or item.reason not in valid_exclusion_reasons
        for item in exclusions
    ):
        raise GeneUniverseError("GEARS roster exclusions are invalid")
    exclusion_keys = [
        (
            item.token.encode("utf-8"),
            item.canonical_gene.encode("utf-8"),
            item.reason,
            item.gene.encode("utf-8"),
        )
        for item in exclusions
    ]
    if len(set(exclusion_keys)) != len(exclusion_keys) or exclusion_keys != sorted(exclusion_keys):
        raise GeneUniverseError("GEARS roster exclusions are duplicated or non-canonical")
    n_target = payload["n_target"]
    fill_count = payload["fill_count"]
    if (
        isinstance(n_target, bool)
        or not isinstance(n_target, int)
        or n_target != len(ordered)
        or payload["mandatory_size"] != len(mandatory)
        or fill_count != n_target - len(mandatory)
    ):
        raise GeneUniverseError("GEARS roster size accounting is invalid")
    if (
        not set(mandatory) <= set(ordered)
        or not set(hvg) <= set(mandatory)
        or not set(eligible) <= set(mandatory)
    ):
        raise GeneUniverseError("GEARS roster mandatory/HVG/eligible containment is invalid")
    ordered_index = {gene: index for index, gene in enumerate(ordered)}
    for label, sequence in (
        ("mandatory_genes", mandatory),
        ("response_hvg_ids", hvg),
        ("eligible_perturbation_genes", eligible),
    ):
        positions = [ordered_index[gene] for gene in sequence]
        if positions != sorted(positions):
            raise GeneUniverseError(f"GEARS roster {label} are not in canonical roster order")
    if payload["ordered_roster_sha256"] != sha256_json(list(ordered)):
        raise GeneUniverseError("GEARS ordered roster SHA-256 mismatch")
    basis = payload["normalization_basis"]
    if basis != {
        "gene_order": "U_full",
        "median_library": basis.get("median_library") if isinstance(basis, dict) else None,
        "subset_after_normalize": True,
        "transform": ["normalize_total_median", "log1p"],
    }:
        raise GeneUniverseError("GEARS normalization basis is invalid")
    median = basis["median_library"]
    if (
        isinstance(median, bool)
        or not isinstance(median, (int, float))
        or not np.isfinite(median)
        or median <= 0
    ):
        raise GeneUniverseError("GEARS normalization median is invalid")
    provenance = payload["provenance"]
    provenance_sha_fields = {
        "alias_sha256",
        "control_row_identity_sha256",
        "eligibility_sha256",
        "fit_artifact_content_sha256",
        "full_var_order_sha256",
        "gene2go_sha256",
        "generator_code_sha256",
        "perturbation_candidate_sha256",
        "response_artifact_sha256",
        "response_hvg_sha256",
    }
    expected_provenance = provenance_sha_fields | {"n_target", "raw_data_sha256"}
    if not isinstance(provenance, dict) or set(provenance) != expected_provenance:
        raise GeneUniverseError("GEARS roster provenance has an unexpected key set")
    for field in provenance_sha_fields:
        _require_sha256(provenance.get(field), field=f"provenance.{field}")
    raw_data_sha256 = provenance.get("raw_data_sha256")
    if (
        provenance.get("n_target") != n_target
        or not isinstance(raw_data_sha256, str)
        or not raw_data_sha256
    ):
        raise GeneUniverseError("GEARS roster provenance identity is invalid")
    if provenance["response_hvg_sha256"] != sha256_json(list(hvg)):
        raise GeneUniverseError("GEARS roster response-HVG SHA-256 mismatch")
    return GearsGeneRosterArtifact(
        ordered_roster=ordered,
        n_target=n_target,
        mandatory_genes=mandatory,
        response_hvg_ids=hvg,
        eligible_perturbation_genes=eligible,
        eligibility_exclusions=exclusions,
        fill_count=fill_count,
        provenance=MappingProxyType(dict(provenance)),
        normalization_basis=MappingProxyType(dict(basis)),
        ordered_roster_sha256=payload["ordered_roster_sha256"],
        artifact_checksum=declared,
    )


def assert_gears_roster_matches(
    var_names: Sequence[str], artifact: GearsGeneRosterArtifact
) -> None:
    """Fail unless ``var_names`` exactly equal the ordered method roster."""
    observed = _validated_gene_order(var_names, field="GEARS var_names")
    if observed != artifact.ordered_roster:
        raise GeneUniverseError("GEARS gene roster differs from the frozen artifact")


def normalize_full_then_subset(
    counts_full: sparse.spmatrix | np.ndarray,
    *,
    full_gene_order: Sequence[str],
    response_projection: Mapping[str, object],
    roster: GearsGeneRosterArtifact,
) -> sparse.csr_matrix | np.ndarray:
    """Normalize allowed raw rows over ``U_full``, then select ``R_gears``.

    This is a fit-input transform only. GEARS prediction output contains only
    ``R_gears`` and must not be treated as full-universe raw counts; its scientific
    output bridge remains blocked until Probe A establishes its scale.
    """
    genes = _validated_gene_order(full_gene_order, field="full_gene_order")
    full_sha = canonical_gene_order_sha256(genes)
    if response_projection.get("gene_order_sha256") != full_sha:
        raise GeneUniverseError("response projection does not bind full_gene_order")
    if roster.provenance.get("full_var_order_sha256") != full_sha:
        raise GeneUniverseError("GEARS roster does not bind full_gene_order")
    if roster.provenance.get("response_artifact_sha256") != response_projection.get(
        "response_artifact_sha256"
    ):
        raise GeneUniverseError("GEARS roster does not bind the response artifact")
    raw_hvg = response_projection.get("hvg_gene_ids")
    if not isinstance(raw_hvg, list) or tuple(raw_hvg) != roster.response_hvg_ids:
        raise GeneUniverseError("GEARS roster does not bind the frozen response HVGs")
    if roster.provenance.get("response_hvg_sha256") != sha256_json(raw_hvg):
        raise GeneUniverseError("GEARS roster response-HVG identity mismatch")
    median = response_projection.get("median_library")
    if (
        isinstance(median, bool)
        or not isinstance(median, (int, float))
        or not np.isfinite(median)
        or median <= 0
    ):
        raise GeneUniverseError("response projection median_library is invalid")
    if median != roster.normalization_basis.get("median_library"):
        raise GeneUniverseError("GEARS roster normalization median mismatch")
    if roster.provenance.get("raw_data_sha256") != response_projection.get("raw_data_sha256"):
        raise GeneUniverseError("GEARS roster raw-data identity mismatch")
    index = {gene: i for i, gene in enumerate(genes)}
    try:
        columns = [index[gene] for gene in roster.ordered_roster]
    except KeyError as exc:
        raise GeneUniverseError(f"GEARS roster gene {exc} is absent from U_full") from exc
    shape = getattr(counts_full, "shape", ())
    if len(shape) != 2 or shape[1] != len(genes):
        raise GeneUniverseError("counts_full does not span U_full")

    if sparse.issparse(counts_full):
        matrix = sparse.csr_matrix(counts_full, dtype=np.float64, copy=True)
        if matrix.data.size and (
            not np.all(np.isfinite(matrix.data))
            or np.any(matrix.data < 0)
            or np.any(matrix.data != np.floor(matrix.data))
        ):
            raise GeneUniverseError("counts_full must contain raw non-negative integers")
        library = np.asarray(matrix.sum(axis=1)).ravel()
        scale = np.divide(
            float(median),
            library,
            out=np.zeros_like(library, dtype=np.float64),
            where=library > 0,
        )
        normalized = matrix.multiply(scale[:, None]).tocsr()
        normalized.data = np.log1p(normalized.data)
        return normalized[:, columns].tocsr()

    matrix = np.asarray(counts_full, dtype=np.float64)
    if (
        matrix.ndim != 2
        or not np.all(np.isfinite(matrix))
        or np.any(matrix < 0)
        or np.any(matrix != np.floor(matrix))
    ):
        raise GeneUniverseError("counts_full must be a 2-D raw-count matrix")
    library = matrix.sum(axis=1, keepdims=True)
    safe = np.where(library > 0, library, 1.0)
    normalized = np.log1p(matrix * (float(median) / safe))
    return normalized[:, columns]
