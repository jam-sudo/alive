"""Gene->protein-sequence mapping logic (A100 prep, step 4).

Produces the data-card ``sequences`` JSON: a mapping ``gene -> [protein_seq, ...]``
that encodes the 0/1/>1 convention ``build_feature_bank`` re-classifies (0 =
missing, 1 = usable, >1 = ambiguous).  Keeping the convention here means the
written JSON is the single source of truth for eligibility.

Pure classification + assembly only; the live UniProt fetch is a thin urllib
wrapper in ``scripts/fetch_sequences.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


def parse_uniprot_results(raw: Mapping) -> list[dict[str, str]]:
    """Extract ``[{accession, sequence}, ...]`` from a UniProtKB search response.

    Parameters
    ----------
    raw : Mapping
        The decoded JSON from the UniProtKB REST ``search`` endpoint (the query
        is expected to already constrain organism / reviewed / exact gene).
    """
    entries: list[dict[str, str]] = []
    for r in raw.get("results", []):
        acc = r.get("primaryAccession")
        seq = (r.get("sequence") or {}).get("value")
        if acc and seq:
            entries.append({"accession": acc, "sequence": seq})
    return entries


@dataclass(frozen=True)
class SequenceMapResult:
    """A gene->sequence mapping plus its eligibility breakdown."""

    mapping: dict[str, list[str]]
    n_usable: int
    n_missing: int
    n_ambiguous: int
    exclusions: dict[str, str] = field(default_factory=dict)


def build_sequence_map(per_gene: Mapping[str, list[dict[str, str]]]) -> SequenceMapResult:
    """Assemble the gene->[sequence,...] map from per-gene candidate entries.

    Each gene's candidate list (already filtered to reviewed exact-gene hits) is
    classified by count: 1 = usable, 0 = missing, >1 = ambiguous.  The written
    mapping keeps the raw sequences (``[]`` for missing, all of them for
    ambiguous) so ``build_feature_bank`` re-derives the identical classification.
    """
    mapping: dict[str, list[str]] = {}
    exclusions: dict[str, str] = {}
    n_usable = n_missing = n_ambiguous = 0
    for gene, entries in per_gene.items():
        seqs = [e["sequence"] for e in entries]
        mapping[gene] = seqs
        n = len(seqs)
        if n == 1:
            n_usable += 1
        elif n == 0:
            n_missing += 1
            exclusions[gene] = "missing sequence"
        else:
            n_ambiguous += 1
            exclusions[gene] = "ambiguous mapping"
    return SequenceMapResult(
        mapping=mapping,
        n_usable=n_usable,
        n_missing=n_missing,
        n_ambiguous=n_ambiguous,
        exclusions=exclusions,
    )
