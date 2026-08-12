# COMPOSE-K562-v1 — instructions for the INDEPENDENT archiver of the kernel-isolation CI proof

> **Who this is for.** A third party, outside the session that authored this code, who has agreed to
> archive one Linux kernel-isolation CI run so it can back the COMPOSE seal. It assumes no prior
> knowledge of this repository.
>
> **What it does not do.** It does not engage you — selecting and instructing an actual independent
> party is the owner's step, not this document's. It does not open any seal, read any scientific
> outcome, or authorize any run. COMPOSE is **RELEASE-BLOCKED** with the seal **UNOPENED** and
> archiving does not change that.
>
> Settles the local half of the runbook §2.5 requirement that the archive backing the seal be an
> independent archiver's. Registered in `plans/2026-08-01-compose-pre-pod-local-closure.md` as L5.

## 1. Why an independent archiver is required at all

The GitHub Actions artifact is **transport, not evidence**. It expires. After expiry the committed
archive JSON is the only surviving record of several fields, and nothing in the repository can
re-derive them:

| field | after artifact expiry |
|---|---|
| `junit` block, testcase roster, `workflow_sha256` | reproducible from committed primary bytes |
| `runner.os` / `runner.architecture` / `runner.kernel_release` | **archive JSON only** |
| `interpreter` (v2 receipts) | **archive JSON only** |
| `head_sha`, `run_id`, `run_attempt`, `source_artifact` | **archive JSON only** |

Those archive-only fields are exactly the ones carrying *"this ran on a real x86_64 Linux kernel, at
commit X, under interpreter Y"* — the whole claim. While the artifact is still downloadable anyone
can refute a false archive by re-downloading it; once it expires, the archiver's word is the trust
base. That is why the grade must not come from the party that wrote the code.

**Existing archives and their honest status.** Two are committed under
`docs/activation-evidence/compose/`. The `614017b6…` archive carries an independent Codex review; the
`2dd23d6…` archive's `archived_by` records truthfully that it was produced by agents dispatched by the
authoring session and is therefore **not** independent. Neither is the run that will back the seal.

**This is not hypothetical.** As of 2026-08-12 the `614017b6…` archive's source artifact expired on
`2026-08-08T10:48:54Z` — four days ago. Its `runner.*`, `head_sha`, `run_id` and `source_artifact`
fields are **already** unverifiable by anyone, and its committed JUnit bytes cover only the
reproducible half of the table above. The remaining artifact (`2dd23d6…`) expires
`2026-10-24T11:42:20Z`. Both windows opened before retention was raised to 400 days, which protects
only runs made after the change — including, deliberately, the one that will back the seal.

## 2. What you must NOT do

These are refusals, not preferences. An archive produced any of these ways is not acceptable and
some of them the tool will reject outright:

- **Do not hand-assemble the archive JSON.** Not from the run's web page, not from `gh` metadata, not
  by editing an existing archive. The tool reads the downloaded ZIP itself; that is the point of it.
- **Do not record only a run URL** or a run ID as the evidence.
- **Do not archive an artifact you did not download yourself.** If someone hands you a ZIP, you are
  grading their download, not the run.
- **Do not edit any field of the receipt inside the ZIP.** The archive binds the receipt's own
  checksum; a single changed byte is detected.
- **Do not write `archived_by` as anything that does not name you.** See §6 — this is the one field
  no validator can enforce.

## 3. Preconditions

1. A green Linux kernel-isolation CI run whose artifact has **not yet expired**. Retention is 400
   days from the run (`.github/workflows/test-suite.yml`, `retention-days: 400`), but confirm the
   real expiry per §4.2 rather than computing it.
2. A clone of the repository and `uv` available. Run `uv sync --locked` — never bare `uv sync`, which
   rewrites `uv.lock`; that file is inside the isolation closure and rewriting it turns the closure
   test red until a fresh run is archived.
3. Read access to the repository's Actions artifacts (`gh auth status` should show a valid login).

## 4. Procedure

### 4.1 Identify the run

```bash
gh run list --branch main --workflow test-suite.yml --limit 10 \
  --json databaseId,headSha,conclusion,createdAt
```

Record the `databaseId` (the run ID) and `headSha`. The run must have concluded `success`.

### 4.2 Observe the artifact, and record what you observe

```bash
gh api repos/<owner>/<repo>/actions/runs/<RUN_ID>/artifacts \
  --jq '.artifacts[] | "\(.id)  \(.name)  \(.size_in_bytes)  expires \(.expires_at)"'
```

The artifact is named `junit-<headSha>`. **Copy the `id` and `expires_at` verbatim into §4.4** — do
not compute the expiry from the run date and do not round it. These become
`source_artifact.artifact_id` and `source_artifact.expires_at_utc`, and after expiry they are
unverifiable, so a value you derived rather than observed is a value nobody can ever check.

### 4.3 Download the artifact yourself

```bash
gh api repos/<owner>/<repo>/actions/artifacts/<ARTIFACT_ID>/zip > artifact.zip
mkdir -p extracted && (cd extracted && unzip -o ../artifact.zip)
```

`extracted/` must contain **exactly** `junit.xml` and `kernel-isolation-ci-receipt.json` — for a v2
proof profile the tool requires both members and no others, no directories, and no duplicate names.

### 4.4 Build the archive

```bash
uv run python scripts/compose/archive_kernel_isolation_ci_receipt.py \
  --receipt          extracted/kernel-isolation-ci-receipt.json \
  --artifact-archive artifact.zip \
  --artifact-id      <ARTIFACT_ID observed in 4.2> \
  --artifact-name    junit-<headSha> \
  --expires-at-utc   <expires_at observed in 4.2> \
  --archived-at-utc  <the UTC instant you are running this> \
  --archived-by      "<your identity — see section 6>" \
  --output           docs/activation-evidence/compose/kernel_isolation_ci_<headSha>.json
```

The output path is write-once; it will refuse to overwrite an existing file.

### 4.5 Also preserve the primary JUnit bytes

```bash
cp extracted/junit.xml \
   docs/activation-evidence/compose/kernel_isolation_junit_<headSha>.xml
```

This is what keeps the `junit` block, testcase roster and `workflow_sha256` reproducible after the
artifact expires. Skipping it is the difference between "tamper-evident and partially reproducible"
and "tamper-evident only".

## 5. What the tool verifies for you

So you know which parts are machine-checked and which rest on your care. `build_kernel_isolation_ci_archive`
reads the ZIP directly and refuses unless:

- the receipt validates on its own terms (schema roster, `self_checksum`, Linux x86_64 runner, JUnit
  totals self-consistent with zero failures and zero errors, both required kernel testcases present
  and passed, and — for a `..._receipt_v2` receipt — a well-formed `interpreter` block whose build
  string agrees with its version);
- the ZIP's member roster is exactly the expected one, with no directories, duplicates, or
  oversized members;
- the ZIP's `junit.xml` hashes **byte-identically** to the digest inside the receipt;
- for a v2 profile, the ZIP's embedded receipt is byte-identical to the canonical one.

You cannot make a plausible-looking archive out of unrelated files. What you *can* do, and what no
code can stop, is §6.

## 6. `archived_by` — the field nothing enforces

`archived_by` is validated only as a non-empty string. **No check anywhere constrains its content.**
It is the single field separating an independent grade from a self-review, and it is verified by the
owner reading it, not by any test.

Write who you actually are and what you actually did. State your relationship to the authoring
session plainly, including if there is one. If you did not personally download the artifact, say so —
an honest weaker grade is usable evidence; an overstated one silently corrupts the trust base of
everything downstream.

## 7. A trap in verification — do not misread it as tampering

Re-deriving an archived receipt from a **later** commit fails with:

```
kernel-isolation workflow differs from the blob recorded at the commit under test
```

This is **expected and is not evidence of tampering.** The receipt binds `workflow_sha256` to the
workflow blob as recorded at that run's own `head_sha`, and both `.github/workflows/test-suite.yml`
and the receipt builder have legitimately changed since earlier archives. Verify from a worktree at
the archived commit:

```bash
git worktree add /tmp/verify-<headSha> <headSha>
```

Reporting this message as a tamper finding has happened before and wastes a review round.

## 8. What to hand back

1. The two written files from §4.4 and §4.5.
2. The three digests the archiver prints (`..._archive_sha256`, `..._archive_file_sha256`,
   `..._archive_self_checksum`).
3. The run ID, artifact ID, artifact name and observed expiry, as you observed them in §4.2.
4. A one-paragraph statement of your independence, matching what you wrote in `archived_by`.

Do not commit these yourself unless the owner asks. Which commit the evidence lands on interacts with
the runbook §2.5 `approved_git_sha == runtime HEAD` binding, and that ordering is the owner's to
decide — see the unresolved `head_sha == C` decision in the runbook.
