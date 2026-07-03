# COMPOSE Fit-Role Artifact Library (A1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the leakage-safe fit-role AnnData artifact library — a metadata-before-X extractor, a deterministic `.h5ad` generator, a re-validating loader with path safety, and canonical content-identity hashing — so sub-project A2 (payload-v2 protocol) can reference an immutable, audited fit-role artifact.

**Architecture:** One new module `src/alive/compose/fit_role.py` plus a thin CLI. The extractor selects `{control, singles, combo_calibration}` rows from `obs` metadata and asserts sealed-disjointness **before** any expression matrix is read, so sealed expression is never materialized. The generator writes an immutable `.h5ad` (raw CSR counts, full gene universe) and binds a canonical `content_manifest_sha256` (row/gene/CSR-data identity, invariant to HDF5 layout) alongside the file SHA. The validator re-reads and re-checks every digest + role closure + path policy.

**Tech Stack:** Python 3.12, `anndata`/`scanpy` (deps in `pyproject.toml`), `scipy.sparse` CSR, `numpy`, `alive.provenance.sha256_json`, `pytest`, `ruff`.

## Global Constraints

- Container is AnnData `.h5ad`; `X` holds **raw integer UMI counts** over the **full measured gene universe** (spec §3; CLAUDE.md §7). Never globally densify — slice bounded row subsets only.
- Artifact obs `role` ∈ exactly `{control, singles, combo_calibration}`; **no sealed role or sealed pair ever present** (spec §3.1). Sealed rows' expression must be **unmaterializable** by the extractor (spec §4).
- `sha256_json(obj)` returns **bare lowercase hex** (`src/alive/provenance.py:123`). Content/gene/row digests use it directly (hex). The artifact **file** `sha256` field is `"sha256:" + hex` of the file bytes (spec §2.1).
- `content_manifest_sha256` is the reproducibility criterion (logical identity); the file SHA is transport/immutability only. CSR is canonicalized with `sort_indices()` + `sum_duplicates()` + fixed dtype **before** hashing (spec §3.2).
- This work opens **no seal** and touches **no real Norman** data; all tests use tiny synthetic `scipy.sparse` fixtures built in `tmp_path` (never a committed `.h5ad` — `*.h5ad` is gitignored). Real generation runs on the dev pod (spec §4/§10).
- Run tests with `uv run pytest` (anndata is only importable in the project venv). Ruff line length 100.
- Errors are `FitRoleArtifactError(ValueError)`; every validation failure raises (fail-closed) — never a silent skip (spec §5/§9).

Spec: `docs/superpowers/specs/2026-07-02-compose-fit-data-contract-design.md` (this is sub-project A, first half A1 = §2.1 identity fields, §3, §3.1, §3.2, §4, §5, §5.1 items 1–4/6–10, §7.1 artifact functions, §8 artifact tests). The `response_projection`/payload-v2/envelope/worker/phase2a wiring is **A2 (a separate plan)** and out of scope here.

---

### Task 1: Canonical content-identity hashing

**Files:**
- Create: `src/alive/compose/fit_role.py`
- Test: `tests/alive/compose/test_fit_role.py`

**Interfaces:**
- Consumes: `alive.provenance.sha256_json(obj) -> str` (bare hex).
- Produces:
  - `class FitRoleArtifactError(ValueError)`
  - `canonical_gene_order_sha256(var_names: Sequence[str]) -> str` (bare hex)
  - `row_identity_sha256(rows: Sequence[tuple[str, str, str]]) -> str` (bare hex; rows are `(source_row_id, role, canonical_perturbation)` in artifact row order)
  - `content_manifest_sha256(*, schema_version: int, X: sparse.csr_matrix, var_names: Sequence[str], rows: Sequence[tuple[str, str, str]], provenance: Mapping[str, str], role_counts: Mapping[str, int]) -> str` (bare hex)

- [ ] **Step 1: Write the failing tests**

```python
# tests/alive/compose/test_fit_role.py
from __future__ import annotations

import numpy as np
import pytest
from scipy import sparse

from alive.compose.fit_role import (
    FitRoleArtifactError,
    canonical_gene_order_sha256,
    content_manifest_sha256,
    row_identity_sha256,
)


def _csr(rows: list[list[float]]) -> sparse.csr_matrix:
    return sparse.csr_matrix(np.asarray(rows, dtype=np.float64))


def test_gene_order_digest_is_order_sensitive_and_rejects_bad_ids():
    a = canonical_gene_order_sha256(["G1", "G2", "G3"])
    assert a == canonical_gene_order_sha256(["G1", "G2", "G3"])  # deterministic
    assert a != canonical_gene_order_sha256(["G2", "G1", "G3"])  # order matters
    with pytest.raises(FitRoleArtifactError):
        canonical_gene_order_sha256(["G1", "G1"])  # duplicate
    with pytest.raises(FitRoleArtifactError):
        canonical_gene_order_sha256(["G1", ""])  # empty


def test_content_manifest_is_invariant_to_csr_storage_layout():
    # Same logical matrix, two different CSR internal layouts (unsorted indices,
    # explicit zero / duplicate) must hash identically.
    dense = [[0.0, 2.0, 0.0], [1.0, 0.0, 3.0]]
    clean = _csr(dense)
    messy = sparse.csr_matrix(([2.0, 3.0, 1.0], ([0, 1, 1], [1, 2, 0])), shape=(2, 3))
    rows = [("r0", "control", "control"), ("r1", "singles", "KLF1")]
    prov = {"raw_data_sha256": "x"}
    counts = {"control": 1, "singles": 1, "combo_calibration": 0}
    kw = dict(schema_version=1, var_names=["G1", "G2", "G3"], rows=rows, provenance=prov, role_counts=counts)
    assert content_manifest_sha256(X=clean, **kw) == content_manifest_sha256(X=messy, **kw)


def test_content_manifest_changes_when_logical_content_changes():
    rows = [("r0", "control", "control")]
    kw = dict(
        schema_version=1, var_names=["G1", "G2"], rows=rows,
        provenance={"raw_data_sha256": "x"}, role_counts={"control": 1, "singles": 0, "combo_calibration": 0},
    )
    base = content_manifest_sha256(X=_csr([[1.0, 2.0]]), **kw)
    assert base != content_manifest_sha256(X=_csr([[1.0, 9.0]]), **kw)  # data changed
    assert base != content_manifest_sha256(X=_csr([[1.0, 2.0]]), **{**kw, "var_names": ["G2", "G1"]})


def test_row_identity_digest_is_row_order_sensitive():
    a = row_identity_sha256([("r0", "control", "control"), ("r1", "singles", "KLF1")])
    b = row_identity_sha256([("r1", "singles", "KLF1"), ("r0", "control", "control")])
    assert a != b
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/alive/compose/test_fit_role.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'alive.compose.fit_role'`.

- [ ] **Step 3: Write the module + hashing implementation**

```python
# src/alive/compose/fit_role.py
"""Leakage-safe fit-role AnnData artifact library (COMPOSE sub-project A1).

Extractor (metadata before X), deterministic .h5ad generator, re-validating
loader with path safety, and canonical content-identity hashing. See
docs/superpowers/specs/2026-07-02-compose-fit-data-contract-design.md
§2.1/§3/§3.2/§4/§5.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

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
    m = sparse.csr_matrix(X, dtype=_CSR_DTYPE)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/alive/compose/test_fit_role.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/fit_role.py tests/alive/compose/test_fit_role.py
git commit -m "feat(compose): canonical fit-role content-identity hashing (A1 task 1)"
```

---

### Task 2: Metadata-before-X extractor (leakage boundary)

**Files:**
- Modify: `src/alive/compose/fit_role.py`
- Test: `tests/alive/compose/test_fit_role.py`

**Interfaces:**
- Consumes: `_ALLOWED_ROLES`, `FitRoleArtifactError` (Task 1).
- Produces:
  - `@dataclass(frozen=True) class FitRoleExtraction` with fields: `X: sparse.csr_matrix`, `var_names: tuple[str, ...]`, `rows: tuple[tuple[str, str, str], ...]` (source_row_id, role, canonical_perturbation), `role_counts: dict[str, int]`, `raw_data_sha256: str`, `pair_manifest_sha256: str`, `eligibility_hash: str`.
  - `class ComposeFitRoleExtractor` — `__init__(self, *, obs_role: Sequence[str], obs_source_row_id: Sequence[str], obs_perturbation: Sequence[str], var_names: Sequence[str], calibration_pair_ids: Sequence[tuple[str, str]], sealed_pair_ids: Sequence[tuple[str, str]], raw_data_sha256: str, pair_manifest_sha256: str, eligibility_hash: str, row_reader: Callable[[list[int]], sparse.csr_matrix])`; methods `select_row_ids() -> list[int]` and `extract() -> FitRoleExtraction`.
  - `extract_fit_roles(*, extractor: ComposeFitRoleExtractor) -> FitRoleExtraction`
- Note: `row_reader(idx)` reads **only** the given rows (backed slicing in production; an injected spy in tests). `select_row_ids()` uses obs metadata only and never calls `row_reader`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/alive/compose/test_fit_role.py
from alive.compose.fit_role import ComposeFitRoleExtractor, FitRoleExtraction, extract_fit_roles


def _extractor(**overrides):
    # 6 rows: 0 control, 1-2 singles, 3 combo_calibration, 4-5 sealed (double-unseen)
    obs_role = ["control", "singles", "singles", "combo_calibration", "singles", "singles"]
    obs_src = [f"r{i}" for i in range(6)]
    obs_pert = ["control", "KLF1", "CEBPE", "CEBPE_KLF1", "AAA", "BBB"]
    var_names = ["G1", "G2", "G3"]
    full = sparse.csr_matrix(np.arange(1, 19, dtype=np.float64).reshape(6, 3))
    sealed_rows = {4, 5}

    def row_reader(idx: list[int]) -> sparse.csr_matrix:
        if any(i in sealed_rows for i in idx):
            raise AssertionError(f"sealed row read attempted: {sorted(set(idx) & sealed_rows)}")
        return full[idx]

    kw = dict(
        obs_role=obs_role, obs_source_row_id=obs_src, obs_perturbation=obs_pert,
        var_names=var_names, calibration_pair_ids=[("CEBPE", "KLF1")],
        sealed_pair_ids=[("AAA", "BBB")], raw_data_sha256="raw", pair_manifest_sha256="pm",
        eligibility_hash="elig", row_reader=row_reader,
    )
    kw.update(overrides)
    return ComposeFitRoleExtractor(**kw)


def test_extract_selects_only_allowed_rows_and_never_reads_sealed():
    ex = _extractor()
    assert ex.select_row_ids() == [0, 1, 2, 3]  # sealed rows 4,5 excluded
    extraction = extract_fit_roles(extractor=ex)  # row_reader raises if sealed touched
    assert extraction.X.shape == (4, 3)
    assert extraction.role_counts == {"control": 1, "singles": 2, "combo_calibration": 1}
    assert extraction.rows[3] == ("r3", "combo_calibration", "CEBPE_KLF1")


def test_extract_rejects_combo_calibration_pair_not_in_calibration_set():
    # r3 relabeled to a pair that is NOT a registered calibration pair -> abort
    ex = _extractor(obs_perturbation=["control", "KLF1", "CEBPE", "AAA_BBB", "AAA", "BBB"])
    with pytest.raises(FitRoleArtifactError):
        ex.select_row_ids()


def test_extract_rejects_unknown_role_before_reading_x():
    ex = _extractor(obs_role=["control", "singles", "singles", "sealed_double_unseen", "singles", "singles"])
    with pytest.raises(FitRoleArtifactError):
        ex.select_row_ids()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/alive/compose/test_fit_role.py -q`
Expected: FAIL with `ImportError: cannot import name 'ComposeFitRoleExtractor'`.

- [ ] **Step 3: Implement the extractor**

```python
# add imports at top of src/alive/compose/fit_role.py
from collections.abc import Callable
from dataclasses import dataclass


def _canonical_pair(perturbation: str) -> tuple[str, str]:
    a, b = perturbation.split("_", 1)
    return (a, b) if a.encode("utf-8") < b.encode("utf-8") else (b, a)


@dataclass(frozen=True)
class FitRoleExtraction:
    """Allowed-row-only extraction: the input to the artifact generator."""

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
        self._raw_data_sha256 = str(raw_data_sha256)
        self._pair_manifest_sha256 = str(pair_manifest_sha256)
        self._eligibility_hash = str(eligibility_hash)
        self._row_reader = row_reader
        if len(set(self._src)) != n:
            raise FitRoleArtifactError("source_row_id must be unique")

    def select_row_ids(self) -> list[int]:
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
                    raise FitRoleArtifactError(f"row {i}: pair {pair!r} not a registered calibration pair")
            elif role == "singles" and ("_" in pert or pert == "control"):
                raise FitRoleArtifactError(f"row {i}: singles label {pert!r} is not a single gene")
            elif role == "control" and pert != "control":
                raise FitRoleArtifactError(f"row {i}: control label {pert!r} is not 'control'")
            selected.append(i)
        return selected

    def extract(self) -> FitRoleExtraction:
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
    """Public entry point: run the audited extractor once."""
    return extractor.extract()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/alive/compose/test_fit_role.py -q`
Expected: PASS (7 tests total).

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/fit_role.py tests/alive/compose/test_fit_role.py
git commit -m "feat(compose): metadata-before-X fit-role extractor with sealed leakage guard (A1 task 2)"
```

---

### Task 3: Immutable `.h5ad` generator + `FitRoleArtifactSpec`

**Files:**
- Modify: `src/alive/compose/fit_role.py`
- Test: `tests/alive/compose/test_fit_role.py`

**Interfaces:**
- Consumes: `FitRoleExtraction` (Task 2), `content_manifest_sha256`/`canonical_gene_order_sha256`/`row_identity_sha256` (Task 1).
- Produces:
  - `@dataclass(frozen=True) class FitRoleArtifactSpec` — `path: str`, `sha256: str` (`"sha256:"+hex`), `content_manifest_sha256: str`, `raw_data_sha256: str`, `pair_manifest_sha256: str`, `eligibility_hash: str`, `row_identity_sha256: str`, `gene_order_sha256: str`, `n_cells: int`, `n_genes: int`, `role_counts: dict[str, int]`; method `to_payload_block() -> dict` (the spec §2.1 `fit_role_artifact` block).
  - `generate_fit_role_artifact(*, extraction: FitRoleExtraction, out_path: str, config_sha256: str, data_card_sha256: str, calibration_gene_set_hash: str, generator_code_sha256: str, writer_environment_sha256: str) -> FitRoleArtifactSpec`
- `_ARTIFACT_SCHEMA_VERSION = 1` module constant.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/alive/compose/test_fit_role.py
from pathlib import Path

from alive.compose.fit_role import FitRoleArtifactSpec, generate_fit_role_artifact


def _gen(tmp_path: Path, name: str = "art.h5ad", **prov) -> FitRoleArtifactSpec:
    extraction = extract_fit_roles(extractor=_extractor())
    p = dict(config_sha256="cfg", data_card_sha256="dc", calibration_gene_set_hash="cg",
             generator_code_sha256="gen", writer_environment_sha256="env")
    p.update(prov)
    return generate_fit_role_artifact(extraction=extraction, out_path=str(tmp_path / name), **p)


def test_generate_writes_valid_h5ad_and_spec(tmp_path):
    import anndata as ad

    spec = _gen(tmp_path)
    assert spec.sha256.startswith("sha256:")
    assert spec.n_cells == 4 and spec.n_genes == 3
    assert spec.role_counts == {"control": 1, "singles": 2, "combo_calibration": 1}
    adata = ad.read_h5ad(spec.path)
    assert set(map(str, adata.obs["role"].unique())) <= {"control", "singles", "combo_calibration"}
    assert "source_row_id" in adata.obs
    block = spec.to_payload_block()
    assert block["allowed_obs_roles"] == ["control", "singles", "combo_calibration"]
    assert block["counts_location"] == "X"


def test_generate_is_content_deterministic(tmp_path):
    a = _gen(tmp_path, "a.h5ad")
    b = _gen(tmp_path, "b.h5ad")
    assert a.content_manifest_sha256 == b.content_manifest_sha256  # logical identity stable
    assert a.gene_order_sha256 == b.gene_order_sha256


def test_generate_is_write_once(tmp_path):
    _gen(tmp_path, "once.h5ad")
    with pytest.raises(FitRoleArtifactError):
        _gen(tmp_path, "once.h5ad")  # refuse to overwrite
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/alive/compose/test_fit_role.py -q`
Expected: FAIL with `ImportError: cannot import name 'generate_fit_role_artifact'`.

- [ ] **Step 3: Implement the generator**

```python
# add imports at top of src/alive/compose/fit_role.py
import hashlib
import os

# module constant near the top
_ARTIFACT_SCHEMA_VERSION = 1


def _file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


@dataclass(frozen=True)
class FitRoleArtifactSpec:
    """Immutable identity of a written fit-role artifact (spec §2.1)."""

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
        """The spec §2.1 ``fit_role_artifact`` payload block."""
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
    """Write an immutable fit-role ``.h5ad`` and bind its canonical identity."""
    import anndata as ad
    import pandas as pd

    if os.path.exists(out_path):
        raise FitRoleArtifactError(f"refusing to overwrite existing artifact: {out_path}")

    X = sparse.csr_matrix(extraction.X)
    data = X.data
    if data.size and (not np.all(np.isfinite(data)) or np.any(data < 0) or np.any(data != np.floor(data))):
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
        schema_version=_ARTIFACT_SCHEMA_VERSION, X=X, var_names=extraction.var_names,
        rows=extraction.rows, provenance=provenance, role_counts=extraction.role_counts,
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
        for s, r, p in zip(reloaded.obs["source_row_id"], reloaded.obs["role"], reloaded.obs["perturbation"])
    )
    rb_manifest = content_manifest_sha256(
        schema_version=_ARTIFACT_SCHEMA_VERSION, X=sparse.csr_matrix(reloaded.X),
        var_names=[str(v) for v in reloaded.var_names], rows=rb_rows,
        provenance=dict(reloaded.uns["provenance"]), role_counts=extraction.role_counts,
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/alive/compose/test_fit_role.py -q`
Expected: PASS (10 tests total).

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/fit_role.py tests/alive/compose/test_fit_role.py
git commit -m "feat(compose): immutable fit-role .h5ad generator + FitRoleArtifactSpec (A1 task 3)"
```

---

### Task 4: Re-validating loader + path safety + negative-leakage suite

**Files:**
- Modify: `src/alive/compose/fit_role.py`
- Test: `tests/alive/compose/test_fit_role.py`

**Interfaces:**
- Consumes: `FitRoleArtifactSpec` (Task 3), `content_manifest_sha256` (Task 1).
- Produces: `validate_fit_role_artifact(path: str, *, spec: FitRoleArtifactSpec, approved_root: str, calibration_pair_ids: Sequence[tuple[str, str]], sealed_pair_ids: Sequence[tuple[str, str]]) -> None` — raises `FitRoleArtifactError` on any mismatch. This is the exact guard a worker runs before fit (spec §5).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/alive/compose/test_fit_role.py
import os as _os

from alive.compose.fit_role import validate_fit_role_artifact

_CALIB = [("CEBPE", "KLF1")]
_SEALED = [("AAA", "BBB")]


def _validate(spec, approved_root, **over):
    kw = dict(spec=spec, approved_root=approved_root, calibration_pair_ids=_CALIB, sealed_pair_ids=_SEALED)
    kw.update(over)
    validate_fit_role_artifact(spec.path, **kw)


def test_validate_happy_path(tmp_path):
    spec = _gen(tmp_path)
    _validate(spec, str(tmp_path))  # no raise


def test_validate_rejects_file_sha_mismatch(tmp_path):
    spec = _gen(tmp_path)
    tampered = FitRoleArtifactSpec(**{**spec.__dict__, "sha256": "sha256:" + "0" * 64})
    with pytest.raises(FitRoleArtifactError):
        _validate(tampered, str(tmp_path))


def test_validate_rejects_content_manifest_mismatch(tmp_path):
    spec = _gen(tmp_path)
    tampered = FitRoleArtifactSpec(**{**spec.__dict__, "content_manifest_sha256": "deadbeef"})
    with pytest.raises(FitRoleArtifactError):
        _validate(tampered, str(tmp_path))


def test_validate_rejects_path_outside_approved_root(tmp_path):
    spec = _gen(tmp_path)
    with pytest.raises(FitRoleArtifactError):
        _validate(spec, str(tmp_path / "other_root"))


def test_validate_rejects_symlink(tmp_path):
    spec = _gen(tmp_path)
    link = tmp_path / "link.h5ad"
    _os.symlink(spec.path, link)
    linked = FitRoleArtifactSpec(**{**spec.__dict__, "path": str(link)})
    with pytest.raises(FitRoleArtifactError):
        _validate(linked, str(tmp_path))


def test_validate_rejects_sealed_pair_in_obs(tmp_path):
    # generate an artifact whose sole calibration pair IS a sealed pair, bypassing
    # the extractor, then validate against the real sealed set -> reject.
    ex = _extractor(
        obs_role=["control", "combo_calibration"], obs_source_row_id=["r0", "r1"],
        obs_perturbation=["control", "AAA_BBB"], calibration_pair_ids=[("AAA", "BBB")],
        sealed_pair_ids=[],  # bypass extractor guard to forge the artifact
    )
    extraction = extract_fit_roles(extractor=ex)
    spec = generate_fit_role_artifact(
        extraction=extraction, out_path=str(tmp_path / "forged.h5ad"),
        config_sha256="c", data_card_sha256="d", calibration_gene_set_hash="g",
        generator_code_sha256="x", writer_environment_sha256="e",
    )
    with pytest.raises(FitRoleArtifactError):  # validated against the REAL sealed set
        _validate(spec, str(tmp_path), calibration_pair_ids=[("AAA", "BBB")], sealed_pair_ids=[("AAA", "BBB")])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/alive/compose/test_fit_role.py -q`
Expected: FAIL with `ImportError: cannot import name 'validate_fit_role_artifact'`.

- [ ] **Step 3: Implement the validator**

```python
# add to src/alive/compose/fit_role.py
def _assert_canonical_path(path: str, approved_root: str) -> str:
    ap = os.path.realpath(os.path.abspath(path))
    root = os.path.realpath(os.path.abspath(approved_root))
    if os.path.islink(path):
        raise FitRoleArtifactError(f"artifact path is a symlink: {path}")
    if not os.path.isfile(ap):
        raise FitRoleArtifactError(f"artifact path is not a regular file: {path}")
    if os.path.commonpath([ap, root]) != root:
        raise FitRoleArtifactError(f"artifact path escapes approved_root: {path}")
    return ap


def validate_fit_role_artifact(
    path: str,
    *,
    spec: FitRoleArtifactSpec,
    approved_root: str,
    calibration_pair_ids: Sequence[tuple[str, str]],
    sealed_pair_ids: Sequence[tuple[str, str]],
) -> None:
    """Re-read the artifact and re-check path policy + every identity digest +
    role closure + sealed-pair absence. The guard a worker runs before fit."""
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
    for role, pert in zip(roles, perts):
        if role == "combo_calibration":
            pair = _canonical_pair(pert)
            if pair in sealed:
                raise FitRoleArtifactError(f"sealed pair present in artifact obs: {pair!r}")
            if pair not in calib:
                raise FitRoleArtifactError(f"combo pair not in calibration set: {pair!r}")

    var_names = [str(v) for v in adata.var_names]
    rows = tuple((str(s), r, p) for s, r, p in zip(adata.obs["source_row_id"], roles, perts))
    role_counts = {r: sum(1 for _, rr, _ in rows if rr == r) for r in sorted(_ALLOWED_ROLES)}
    if canonical_gene_order_sha256(var_names) != spec.gene_order_sha256:
        raise FitRoleArtifactError("gene_order digest mismatch")
    if row_identity_sha256(rows) != spec.row_identity_sha256:
        raise FitRoleArtifactError("row_identity digest mismatch")
    recomputed = content_manifest_sha256(
        schema_version=_ARTIFACT_SCHEMA_VERSION, X=sparse.csr_matrix(adata.X), var_names=var_names,
        rows=rows, provenance=dict(adata.uns["provenance"]), role_counts=role_counts,
    )
    if recomputed != spec.content_manifest_sha256:
        raise FitRoleArtifactError("content_manifest digest mismatch")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/alive/compose/test_fit_role.py -q`
Expected: PASS (16 tests total).

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/fit_role.py tests/alive/compose/test_fit_role.py
git commit -m "feat(compose): re-validating fit-role loader with path safety + leakage suite (A1 task 4)"
```

---

### Task 5: Pod CLI entry point + full-suite green

**Files:**
- Create: `scripts/compose/build_fit_role_artifact.py`
- Test: `tests/alive/compose/test_fit_role_cli.py`

**Interfaces:**
- Consumes: `extract_fit_roles`, `generate_fit_role_artifact`, `validate_fit_role_artifact`, `FitRoleArtifactError` (Tasks 2–4).
- Produces: `build_fit_role_cli(argv: list[str] | None = None) -> int` — a thin library-over-CLI. (Real source/split loading is the driver's job, sub-project C; this CLI only wires the library and is exercised on a fixture.)

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_fit_role_cli.py
from __future__ import annotations

from scripts.compose.build_fit_role_artifact import build_fit_role_cli


def test_cli_module_importable_and_reports_usage():
    # The CLI is a thin wrapper; invoked with no subcommand it returns non-zero
    # rather than raising, so the pod entry point fails closed.
    assert build_fit_role_cli([]) != 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_fit_role_cli.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.compose.build_fit_role_artifact'`.

- [ ] **Step 3: Implement the CLI**

```python
# scripts/compose/build_fit_role_artifact.py
#!/usr/bin/env python
"""Pod CLI: extract fit roles -> write immutable .h5ad -> validate (A1).

Thin wrapper over ``alive.compose.fit_role``. The RunSpec/source/split assembly
that feeds real digests is the production driver's job (sub-project C); this
entry point only orchestrates the library and fails closed.
"""

from __future__ import annotations

import argparse
import sys


def build_fit_role_cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build + validate a COMPOSE fit-role artifact")
    ap.add_argument("--run-spec", required=True, help="committed RunSpec path (driver-assembled)")
    ap.add_argument("--out", required=True, help="output .h5ad path under the approved artifacts root")
    try:
        ap.parse_args(argv)
    except SystemExit:
        return 2
    print(
        "error: real source/split assembly is provided by the production driver "
        "(sub-project C); this A1 CLI is a library entry point only.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(build_fit_role_cli())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/alive/compose/test_fit_role_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full compose suite + ruff, then commit**

Run: `uv run pytest tests/alive/compose/test_fit_role.py tests/alive/compose/test_fit_role_cli.py -q && uv run ruff check src/alive/compose/fit_role.py scripts/compose/build_fit_role_artifact.py tests/alive/compose/test_fit_role.py tests/alive/compose/test_fit_role_cli.py && uv run ruff format --check src/alive/compose/fit_role.py`
Expected: all PASS, ruff clean.

```bash
git add scripts/compose/build_fit_role_artifact.py tests/alive/compose/test_fit_role_cli.py
git commit -m "feat(compose): fit-role artifact pod CLI entry point (A1 task 5)"
```

---

## Notes for the executor

- **Out of scope (A2):** `response_projection` block, `build_response_projection`, payload-v2 schema in `baseline_subprocess.py`, the `{predictions, execution_manifest}` envelope, the reference/stub worker, and the `phase2a.build_subprocess_fit_payload` wiring. A1 stops at the validated fit-role artifact + its `FitRoleArtifactSpec.to_payload_block()`.
- **Real-data generation is pod-only.** A1's tests never touch real Norman; the extractor's `row_reader` is backed-AnnData slicing in production and an injected spy in tests. The §5.1 projection-shape reject (item 5) belongs to A2.
- **Science-dev gate:** after all tasks, this increment is gated with the loop-engineering `science-dev` profile (leakage/seal-boundary anchors: extractor materializes no sealed row; roles are metadata-defined). That gate is run by the controller, not an implementer step.
