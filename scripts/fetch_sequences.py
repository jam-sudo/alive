#!/usr/bin/env python
"""Build the data-card ``sequences`` JSON from UniProtKB (A100 prep, step 4).

For each perturbation target gene, query reviewed (Swiss-Prot) human entries and
apply the exactly-one rule (1 = usable, 0 = missing, >1 = ambiguous), writing:
  * the ``gene -> [protein_seq, ...]`` JSON consumed by the data-card, and
  * a provenance/exclusions report (sequence_source = UniProt release;
    id_mapping_version = the query strategy).

Thin urllib wrapper over :mod:`alive.data.sequences` (stdlib only — no new dep).
Note: there is no checkpoint — an interrupted run restarts from scratch.

IMPORTANT: after running, verify coverage against ``inspect_h5ad.py`` — the
*eligible* set is (usable sequence) AND (>= min_cells), and its sealed slice must
clear ``minimum_sealed_perturbations`` (spec §3.2 eligibility-before-split).

Usage
-----
    uv run python scripts/fetch_sequences.py \
        --h5ad data/k562_essential.h5ad --perturbation-key gene \
        --control-value non-targeting --id-type symbol \
        --out data/k562_gene_sequences.json \
        --provenance-out data/k562_sequence_provenance.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from alive.data.sequences import build_sequence_map, parse_uniprot_results

_BASE = "https://rest.uniprot.org/uniprotkb/search"
_UA = {"User-Agent": "alive-cartographer-prep/1.0 (research; contact: owner)"}


def _query_for(gene: str, *, id_type: str, organism: int) -> str:
    if id_type == "symbol":
        term = f"gene_exact:{gene}"
    elif id_type == "ensembl":
        term = f"xref:ensembl-{gene}"
    else:
        raise ValueError(f"unknown id-type {id_type!r} (use 'symbol' or 'ensembl')")
    return f"({term}) AND organism_id:{organism} AND reviewed:true"


def _uniprot_search(gene: str, *, id_type: str, organism: int, timeout: float, retries: int = 2):
    q = _query_for(gene, id_type=id_type, organism=organism)
    url = f"{_BASE}?" + urllib.parse.urlencode(
        {"query": q, "fields": "accession,sequence", "format": "json", "size": "10"}
    )
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=_UA)  # noqa: S310 (https only)
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                release = resp.headers.get("X-UniProt-Release", "unknown")
                raw = json.loads(resp.read().decode("utf-8"))
            return raw, release
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"UniProt fetch failed for {gene!r}: {last_exc}")


def _gene_list(args) -> list[str]:
    if args.genes:
        return [g.strip() for g in Path(args.genes).read_text().splitlines() if g.strip()]
    import anndata  # noqa: PLC0415

    adata = anndata.read_h5ad(args.h5ad, backed="r")
    labels = adata.obs[args.perturbation_key].astype(str)
    return sorted(set(labels.unique()) - {args.control_value})


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fetch gene->protein-sequence map from UniProt.")
    p.add_argument("--h5ad", type=Path, help="AnnData to read target genes from")
    p.add_argument("--perturbation-key")
    p.add_argument("--control-value")
    p.add_argument("--genes", type=Path, help="alternative: a text file with one gene per line")
    p.add_argument("--id-type", choices=("symbol", "ensembl"), default="symbol")
    p.add_argument("--organism-id", type=int, default=9606, help="NCBI taxon id (human=9606)")
    p.add_argument("--out", required=True, type=Path, help="gene->[seq] JSON output")
    p.add_argument("--provenance-out", required=True, type=Path)
    p.add_argument("--sleep", type=float, default=0.2, help="seconds between requests (be polite)")
    p.add_argument("--timeout", type=float, default=30.0)
    args = p.parse_args(argv)

    if not args.genes and not (args.h5ad and args.perturbation_key and args.control_value):
        print(
            "error: provide --genes, OR --h5ad + --perturbation-key + --control-value",
            file=sys.stderr,
        )
        return 2

    genes = _gene_list(args)
    print(f"resolving {len(genes)} genes via UniProt ({args.id_type}, organism {args.organism_id})")

    per_gene: dict[str, list[dict[str, str]]] = {}
    releases: set[str] = set()
    for i, gene in enumerate(genes, 1):
        raw, release = _uniprot_search(
            gene, id_type=args.id_type, organism=args.organism_id, timeout=args.timeout
        )
        if release != "unknown":
            releases.add(release)
        per_gene[gene] = parse_uniprot_results(raw)
        if i % 100 == 0:
            print(f"  {i}/{len(genes)} ...")
        time.sleep(args.sleep)

    if len(releases) > 1:
        print(f"WARNING: multiple UniProt releases seen across the run: {sorted(releases)}")
    release_seen = sorted(releases)[-1] if releases else "unknown"

    res = build_sequence_map(per_gene)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(res.mapping), encoding="utf-8")

    id_mapping_version = f"uniprotkb-search/{args.id_type}/organism={args.organism_id}/reviewed"
    provenance = {
        "sequence_source": f"uniprotkb-{release_seen}",
        "id_mapping_version": id_mapping_version,
        "uniprot_releases_seen": sorted(releases),
        "n_genes": len(genes),
        "n_usable": res.n_usable,
        "n_missing": res.n_missing,
        "n_ambiguous": res.n_ambiguous,
        "exclusions": res.exclusions,
    }
    args.provenance_out.write_text(json.dumps(provenance, indent=2), encoding="utf-8")

    print(
        f"\nusable={res.n_usable}  missing={res.n_missing}  ambiguous={res.n_ambiguous}\n"
        f"  sequences -> {args.out}\n  provenance -> {args.provenance_out}\n"
        f"  use sequence_source={provenance['sequence_source']!r} and "
        f"id_mapping_version={provenance['id_mapping_version']!r} in the data-card.\n"
        f"VERIFY: re-run inspect_h5ad.py and confirm (usable AND >= min_cells) clears the "
        f"sealed-cohort floor before starting the run."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
