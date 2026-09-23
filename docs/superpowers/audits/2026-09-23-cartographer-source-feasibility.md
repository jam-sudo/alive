# Cartographer source feasibility — metadata-only, 2026-09-23

> **2026-09-23 direction correction:** GWPS/time-shift selection is optional and
> deferred, not a blocker for the current goal. The owner-scope request below is
> no longer the next required action. Follow the [goal-alignment contract](../plans/2026-09-22-cartographer-realignment.md#goal-alignment)
> and reassess the existing evidence first. Observations below remain preserved;
> no candidate is selected and no scientific execution is authorized.

Status: candidate triage, **no selected/authorized evaluation source**. Follows the
[follow-up contract draft](../plans/2026-09-23-cartographer-followup-contract-draft.md).
No expression file, checkpoint or outcome matrix was downloaded or inspected.

## Verified source identities

The preserved TG data card identifies Figshare article 20029387, file 35773219,
`K562_essential_raw_singlecell_01.h5ad`. The publisher's
[article API](https://api.figshare.com/v2/articles/20029387) reports version 1,
DOI `10.25452/figshare.plus.20029387.v1`, CC BY 4.0, and three experiments:
K562 genome-scale day 8, K562 essential-scale day 6, and RPE1 essential-scale day 7.
Each has raw/normalized and single-cell/pseudobulk representations. These four
representations are not four independent experiments.

| Candidate | Verified metadata | Disposition |
| --- | --- | --- |
| K562 essential raw single-cell | File 35773219; 10,661,879,995 bytes; publisher MD5 `4f1122ce1c7f13299a68df6459a266d3` | Already TG's source; no new independent holdout established |
| K562 essential normalized or bulk | Alternative processed forms of the same day-6 experiment | Not an independent replication and not a drop-in raw-count substitute |
| K562 genome-wide raw single-cell | File 35775507; 65,830,941,948 bytes; API computed-MD5 field empty | Candidate only; day-8/panel shift, exposure/target overlap and feature/control compatibility unresolved |
| RPE1 essential | Different cell line and day-7 experiment | Existing CT-RPE1 deferral applies; not activated by this task |

Publisher MD5 is registry metadata, not a verified local download SHA256. The
empty GWPS checksum field is not evidence of corruption or permission to omit
verification; authoritative content identity must be established before use.

The [original study](https://pmc.ncbi.nlm.nih.gov/articles/PMC9380471/) describes
the day-6 and day-8 K562 datasets as independent experiments, but also reports
common perturbations and time-point comparisons. Its supplementary comparisons
include transcriptional-response-selected subsets. That does not establish an
outcome-independent ALIVE evaluation universe; those selected subsets must not
be copied as eligibility rules. Separate experimental generation does not prove
absence of prior model/analyst exposure or target-level overlap.

## Interpretation and two reviews

Review 1: same cell line/modality is insufficient for exchangeability. Switching
day 6 to day 8 changes the evaluation setting. A frozen predictor might be used
to measure cross-experiment/time-shift reliability, but that needs an explicit
estimand and compatible preprocessing, controls and evaluation rules. It cannot
be presented as an untouched repeat of TG's original internal split.

Review 2: neither a larger file nor an independent experiment proves independent
unseen-target evaluation. Before using GWPS, compare a metadata-only target/guide
inventory to the frozen predictor's training/development/calibration/evaluation
exposure ledger. Gene, guide, cell and experimental replicate units must remain
separate. Do not infer exact usable N or biological replication from paper-wide
counts. Do not transfer 65.8 GB or provision a pod merely to inspect feasibility.

## Next information needed

1. Outcome-free target/guide and batch/time metadata for the GWPS candidate, with
   provenance and explicit separation from response-derived fields.
2. Existing local exposure records for that exact asset and source-specific feature/
   control compatibility; absence from this one data card is not proof of non-exposure.
3. A decision on whether a time/panel-shift comparison answers the intended next
   claim. If not, seek a different source rather than relabeling the shift.

No candidate is release-ready and no scientific approval is inferred. Current
recommendation is **continue metadata-only feasibility**, not a dataset switch.

## Retrieval evidence

The web reader could not open the Figshare API. A read-only bounded HTTP request
succeeded using `curl --fail --silent --show-error --max-time 30` against the exact
article API above, piped to `jq` projections of id/title/DOI/version/license/files/
references and description. No file download URL was followed. The original paper
was available for targeted reading; a later page request returned a browser-check
page, which was not bypassed. Claims above are limited to successfully retrieved
publisher metadata and paper passages, not a complete supplementary-data audit.

## Exposure and sequencing-manifest checkpoint — 2026-09-23

Bounded local text search covered repository configs/docs, handoff text artifacts
and retained ALIVE-runs JSON/YAML/Markdown/text/log files for `K562_gwps` and file
ID 35775507. Matches in the historical runbook and governance proposal warn against
substitution; no matching run record was found in the retained ALIVE-runs search.
This is **not proof of non-exposure**: unrecorded, remote, binary or differently
named activity is outside that search. No outcome matrices were inspected.

The publisher's [SRA/GEO manifest article](https://api.figshare.com/v2/articles/20022944)
provides sequencing-file routing manifests, including `KD8_raw_files.csv` (file
35774054, 440,594 bytes). Its description maps rows to sequencing lane/gemgroup
file sets. The official download URL is
`https://ndownloader.figshare.com/files/35774054`.

A bounded in-memory metadata retrieval verified the exact published byte count
and MD5 `03f5b9931452f6797ff8abcf15789ec8` before CSV parsing. Observed SHA256:
`5d1860171a2499e05fdca2dd512a6309a8e7e772ff3725cbe17ce04288c2e719`.
The manifest contains 273 rows and 273 distinct gemgroup labels. Columns are
library/gemgroup, numbered read-file entries, and BAM/index/barcode/feature/matrix
locations. No linked FASTQ, BAM, barcode, feature or matrix object was opened.

**Disposition:** this establishes a routing inventory, not 273 biological replicates,
not a target/guide list, and not an eligible evaluation N. It cannot resolve target
overlap or outcome-independent eligibility. Those remain open; do not silently use
lane/gemgroup counts for power or independence claims.

The first unverified download endpoint returned HTML; a permissive CSV parse showed
an HTML header and eight pseudo-rows. That response was rejected as invalid metadata.
The successful retry used the publisher-listed URL, `curl --location --fail
--max-time 30 --max-filesize 1048576`, pipefail, exact byte/MD5 checks, UTF-8 CSV
parsing and an explicit required `gemgroup` header. Only aggregate counts and field
names were emitted, and no local scientific source artifact was changed.

Next: locate an authoritative **outcome-free target/guide annotation**. If only mixed
response tables or the expression container supply it, define a separately reviewed
metadata projection before accessing them; do not broaden this retrieval implicitly.

## Primary-methods and Table S1 location — 2026-09-23

The public [Europe PMC full-text XML](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC9380471/fullTextXML)
was retrieved with a bounded 30-second HTTP request. Paragraph P61 distinguishes
the panels: K562 day 6 uses DepMap 20Q1 common-essential genes and non-targeting
controls; the additional hand-selected targets based on GWPS phenotypes belong
to **RPE1 day 7**, not K562 day 6. This resolves the earlier unverified possibility
of attributing that response-based panel selection to K562 day 6. It does not
establish an untouched GWPS evaluation cohort or eliminate day/panel shift.

The XML maps Table S1 to supplement SD11, file
`NIHMS1812939-supplement-11.xlsx`, publisher size 1,340,869 bytes and MD5
`b7554e4e9e741126067a7d3964a50523`. The main text identifies this table as the
dual-sgRNA library reference. **Only its reference metadata has been inspected**;
the workbook's sheets, fields, target counts and source-specific membership remain
unverified. This is a concrete next metadata candidate, not an established roster.
Before interpreting it, verify content identity and inspect schema; restrict any
projection to library-design identifiers and membership, not response measurements.

Two alternative routes were ruled out without opening their data files:
[Figshare 21632564](https://api.figshare.com/v2/articles/21632564) contains expression,
embedding and differential-expression outputs, not an outcome-free design inventory;
[Figshare 20127869](https://api.figshare.com/v2/articles/20127869) contains expression
matrix archives, including a 48,984,112,805-byte GWPS archive. Neither is needed for
this metadata check. The author's guide-calling repository directory listing exposed
example diagnostic PDFs, not a verified GWPS library inventory; none was opened.

Review 1: designed target membership would support overlap analysis, but cannot
establish observed eligible N, cell sufficiency or independent biological replication.
Review 2: do not treat public paper access, a new workbook or an absent local text
match as evidence of no prior predictor/analyst exposure. Source selection and
scientific activation remain unresolved; no cloud resources or outcome files were used.

## Preserved predictor feasibility — 2026-09-23

Table S1 retrieval remains incomplete: the PMC `/articles/PMC9380471/bin/` path
returned HTTP 404; the `/articles/instance/9380471/bin/` HEAD returned HTTP 200
but `text/html`, 1,817 bytes, not the expected workbook. No workbook was parsed,
no alternate bytes were accepted, and no access challenge was bypassed. The XLSX
skill was inspected, but no workbook analysis/recalculation was performed.

The more fundamental frozen-predictor prerequisite was checked directly. The
preserved TG archive contains both predictor and response-space serializations.
`shasum -a 256 base_predictor.json base_predictor.npz base.json base.npz` matched
the existing 21-file archive manifest for all four files:

| File | SHA256 |
| --- | --- |
| base_predictor.json | `fd231b4025890acfc3807a372dab771f83c86152afac789645f9f6e3e0f1c0d0` |
| base_predictor.npz | `fc86a99501cb706ab52abf838672cb7bf5caf817dd81ecee22dd880cb27183b9` |
| base.json | `dc526f52d47efc4568fcc600671733805beedb9a7995773879042ae93994fdec` |
| base.npz | `f143acfa81355f03ab99e223b537e756172c3706504495b9cf8c6f56feb7c199` |

Graphify's existing graph located `BasePredictor`, `ResponseSpace` and CLI restore
connections; direct source inspection confirmed `src/alive/cli.py:297` restores
both via their readers. No graph rebuild or predictor fit was performed.
Using the existing locked local runtime, the actual production readers succeeded:

```python
p = Path('/Users/jam/ALIVE-runs/pod-archive-2026-09-11/extracted/alive_artifacts_full/cartographer/d18c601b6855b3b1')
b = BasePredictor.read(p / 'base_predictor')
r = ResponseSpace.read(p / 'base')
assert len(set(b.fit_perturbation_ids)) == 740
assert set(b.fit_perturbation_ids) == set(r.fit_perturbation_ids)
```

Observed predictor semantic checksum:
`ba5bec6464c997f1e295632158cf1a09d246d0651fcc82d14285857d58be0be7`;
response-space semantic checksum:
`96bfb75e3d4a74f889480bfc478c6817e4892972e40ddbccc95c55eb3881aa9e`.
Weights shape `(1280, 50)`, ensemble `(20, 1280, 50)`, preserved transformed
controls `(10691, 50)`; both objects identify the same 740 unique fit targets.
Metadata records 8,563 input genes, 2,000 selected genes and
`library_size_10000_log1p` normalization. These are original predictor properties,
not a new sample size or demonstration of day-8 compatibility.

**Decision after two checks:** a preserved executable predictor is available;
retraining is not a prerequisite merely to recover it. Check 1: successful
checksum-verified restoration is narrower than source compatibility or validated
predictions on a new source. Check 2: the stored control population and response
space must stay frozen; replacing either with GWPS-derived fitted quantities would
change predictor identity and requires an explicit contract. Feature-bank coverage,
gene order/transformation compatibility, exposure overlap, calibration roles and
target inventory are still unresolved. No prediction, evaluation, outcome-store
access or cloud operation was performed in this check.

## Feature coverage and input-axis boundary — 2026-09-23

Read-only file SHA256 verification matched the existing archive manifest for
`feature_bank.json` (`461ba578464bdbd4c55f1b61b0a440ef3f82797dea678cbb982cd030648abbcf`),
`feature_bank.npz` (`8aa009420d7cdb3968038f08f624fada46db3b9526d8c7872d8f0daa4ced4112`)
and `manifest.json` (`e85bba50258b522bd04ee0d99c95190b62224248897b7c4517161d7699a958c8`).
Production `FeatureBank.read` restored 1,989 unique identifiers; explicit comparison
of its semantic checksum with the stored metadata passed:
`d1ce21f917cd201354871775e4ede4a8296cd8d2af8a0a5c959369fb954aae35`.
The reader itself does not perform this comparison, and that semantic checksum
does not recompute the raw feature-matrix digest; the separate file hashes above
are therefore material evidence, not redundant checks.

Metadata-only set intersections found all 740 base-train, 411 development, 247
calibration and 247 original evaluation targets represented. All 344 bank targets
outside those roles occur in the original manifest exclusions. None is thereby
certified as a fresh eligible target. All 1,989 standardized-vector calls returned
shape `(1280,)`; no predictions or outcome reads were made. Provenance identifies
ESM `esm2_t33_650M_UR50D`, mean pooling and `uniprotkb-2026_02`. New GWPS target
coverage is still unknown pending the source inventory; do not silently restrict
the candidate universe to old bank membership to avoid encoding missing targets.

Source inspection (`src/alive/data/preprocess.py`, `ResponseSpace.transform`)
established a concrete transfer constraint: transformation checks matrix width,
normalizes across that full input axis, then selects stored column indices. It
does not receive or validate gene identifiers. The saved response artifact contains
2,000 selected IDs/indices and the full width 8,563, **not the complete ordered
8,563-gene identifier list**. Matching width or merely matching the 2,000 selected
genes is insufficient: permuting columns changes their meaning; using a different
normalization universe changes the input even if HVGs agree.

Review 1: obtain the original source's complete ordered axis from verified metadata
and compare it to the candidate before defining any transfer adapter. Do not patch
the frozen transform to refit PCA, reselect HVGs, or normalize on a different gene
universe while calling it the same predictor. Review 2: missing/duplicate gene and
feature policies belong in the new contract before outcomes; silently zero-filling,
dropping genes, refitting standardization, or relabeling old exclusions is not an
authorized shortcut. This is a cross-source compatibility gap, not proof that the
completed same-source TG result is invalid.

The next feasibility work is now bounded to two metadata inventories: the original
ordered expression-gene axis and the candidate target/guide plus expression-gene
axis. Prefer existing preserved metadata; if extraction from an expression container
is needed, specify an outcome-free projection before access. Predictor recovery no
longer requires retraining, but source compatibility and authorization remain open.

## Local inventory and scope decision checkpoint — 2026-09-23

A filename inventory of retained ALIVE-runs and the September-11 pod capture found
no standalone original Replogle ordered gene-axis file. A bounded JSON-key search
(`gene_ids`, `gene_order`, `gene_axis`, files at most 2 MB) in those locations found
no match. Listed H5AD files were COMPOSE fit/probe assets, not the original Replogle
source; none was opened. This is a bounded custody finding, not proof that no copy
exists anywhere. A preceding broad numeric text search matched unrelated hashes and
large Tahoe manifests; its truncated output was not used as absence evidence.

The preserved data card uses `gene_id_key: null` and the original remote path
`/workspace/alive_data/K562_essential_raw_singlecell_01.h5ad`; source code therefore
takes the expression axis from `var_names`. No current availability of that remote
path was inferred from the historical card. Recovering the exact original axis and
candidate inventory remains necessary before any compatible execution can be claimed.

**Owner scope decision needed before selecting the GWPS route:** whether a separately
registered K562 day-6-to-day-8, cross-experiment/time-shift reliability comparison is
an acceptable next actual-data benchmark. Recommendation: yes, *conditional on*
metadata compatibility and exposure review, with no unseen-target claim unless the
eventual claim-unit split actually supports it. It is not a repeat of TG or an
unqualified replication. If that shifted setting is not desired, source selection
must take a different route rather than hiding the shift.

Additional review 1: the shift is part of the scientific question, not an incidental
loader change; measure reliability under that setting without claiming exchangeable
day-6 calibration. Additional review 2: agreeing to the question would authorize
contract development only, not a download, fit, seal or run; exact source/axis,
predictor/feature identity, role isolation, adequacy, reporting and final scientific
execution authorization still must be settled. No milestone completion is claimed.
