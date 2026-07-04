# COMPOSE payload-v2 Protocol (sub-project A2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the deep-baseline subprocess protocol to payload-v2 — carry the A1 fit-role artifact + a serialized native→PCA-50 response operator, wrap predictions in a `{predictions, execution_manifest}` envelope, and make the reference stub worker exercise the real operator path — so real GEARS/CPA (sub-project B, pod-only) can fit leakage-safe cell-level data and return predictions comparable to L1 in the same δ-space.

**Architecture:** Task 0 first closes the two A1 validator gaps on which A2 depends (role/perturbation consistency and spec↔artifact lineage equality). A2 then adds the *projection operator* (serialize `ResponseSpace` → block; reconstruct it in pure numpy worker-side), bumps `baseline_subprocess._SCHEMA_VERSION` to 2 with the two new payload blocks and an envelope prediction format, binds source digests on the response artifact, wires `phase2a.build_subprocess_fit_payload` to emit v2 with cross-source digest equality, and rewrites the stub worker to read the artifact + apply the operator. The approved artifacts root and expected execution identity are trusted activation inputs, never values derived from the payload being validated. No seal is opened; no real Norman is touched; all tests run on CPU with synthetic Norman-shaped fixtures.

**Tech Stack:** Python 3, numpy, scipy.sparse (CSR), anndata/pandas (fixtures only), pytest, `uv run`. No `gears`/`cpa` import anywhere in `src/` or `tests/`.

## Global Constraints

- **No seal, no real data.** A2 opens no seal and never reads real Norman. Every test builds a synthetic Norman-shaped fixture in `tmp_path` (never a committed `.h5ad`; `*.h5ad` is gitignored). (spec §0, §8; `CLAUDE.md` §6.3, §14.)
- **`_SCHEMA_VERSION = 2`** in `baseline_subprocess.py`. `_validate_payload` keeps enforcing `set(payload) == set(_REQUIRED_KEYS)` exact equality; v1 payloads must be rejected. (spec §2, §5.)
- **Two new payload blocks, exact fields (spec §2.1 / §2.2).** `fit_role_artifact` is produced verbatim by `FitRoleArtifactSpec.to_payload_block()` (A1, already merged). `response_projection` has exactly these keys: `response_artifact_sha256, raw_data_sha256, gene_order_sha256, hvg_gene_ids, transform, median_library, pca_mean, pca_components, control_mean, delta_convention`.
- **Digest formats.** File SHAs are `"sha256:" + hex`; content/gene/row/manifest digests are **bare** 64-char hex (`sha256_json`/`sha256_bytes` output). Do not prefix bare digests.
- **Cross-source equality is mandatory (spec §2.2, §7.2, §10).** `response_projection.pca_components == payload["pca_components"]`, `response_projection.control_mean == payload["control_mean"]` (compared via canonical float64 `.hex()`), and `response_projection.raw_data_sha256 == fit_role_artifact.raw_data_sha256`, `response_projection.gene_order_sha256 == fit_role_artifact.gene_order_sha256`. Any mismatch → `PayloadError`.
- **Response artifact equality is not circular.** `response_projection.response_artifact_sha256` must equal the independently verified `Phase2aInputs.response_space_checksum`; comparing fields only within the payload is insufficient.
- **The projection operator is `ResponseSpace`, not a new formula (spec §0, §2.3, §6).** `build_response_projection` serializes `ResponseSpace` state + z-space `control_mean`; the worker-side operator reproduces `ResponseSpace.project` exactly. `transform` field == `alive.compose.response.RESPONSE_TRANSFORM`.
- **Truth δ is invariant:** `δ = mean_i(z(x_i)) - control_mean` (`z_minus_control_mean`), regardless of `prediction_representation`. (spec §2.3, §2.4.)
- **Prediction representation is method-locked, not merely an enum (spec §2.4):** `cell_raw_counts` | `cell_log_normalized` | `raw_pseudobulk_approximation`. The committed GEARS/CPA configuration declares the permitted representation, the backend carries that expected value out-of-band, and the worker manifest must match it. `raw_pseudobulk_approximation` additionally requires a committed approximation-bias report SHA before scientific activation; `null` is permitted only while the method remains an explicit activation blocker. No silent scale choice.
- **Envelope prediction format (spec §7.2, §2.5):** worker output is `{predictions, execution_manifest}`; both are validated together. `execution_manifest` carries `prediction_representation`, adapter version/sha, expected/observed gene-order digests, checkpoint sha, worker/config/resource/environment-lock sha, fit-artifact content sha, combined-request sha, predictions sha.
- **Single fit/checkpoint (spec §0, §2.5):** the worker validates → fits once → writes one immutable checkpoint → predicts the combined pair union once. Never re-fit or re-invoke per double/single regime.
- **Independent worker verification.** The controller recomputes and compares worker SHA, ordered-request SHA, fit-artifact content SHA, checkpoint-file SHA and prediction SHA, and compares adapter/config/resource/environment identities to activation-time expected values. A worker's internally self-consistent manifest is not evidence by itself.
- **Trusted path boundary.** `approved_artifacts_root` is supplied to the backend by the production driver/fixture harness and forwarded to the worker as a separate CLI argument. It is never computed from `fit_role_artifact.path`.
- **Fail-closed, no silent skip (spec §9):** every artifact/payload/projection/worker validation failure raises (`PayloadError` / `FitRoleArtifactError` / `BaselineUnavailable`) and is a pre-seal abort — no comparator drop, no aggregate stand-in, no `verdict2 INVALID` (INVALID is post-seal only).
- **`_assert_no_sealed_reference` still scans the whole v2 payload** including the two new blocks (`baselines_combo.py:203`). New blocks must never carry a sealed token.
- **Style:** ruff line length 100; NumPy-style docstrings on public API; type hints. Run `uv run pytest` and `uv run ruff check` / `uv run ruff format`.

## Design decisions & scope boundaries (read before Task 0)

These refine the spec's illustrative signatures within the approved contract. **The owner reviews this plan before execution — flag any objection here.**

0. **A1 hardening is a blocking prerequisite.** A2 may not proceed until `validate_fit_role_artifact` rejects a combo token under any non-combo role and compares `raw_data_sha256`, `pair_manifest_sha256`, `eligibility_hash`, row/gene digests and counts between the trusted `FitRoleArtifactSpec` and `.h5ad` provenance/content. The negative reproductions from the independent review become regression tests in Task 0.
1. **Operator lives in `fit_role.py`.** Both `build_response_projection` (serialize) and `apply_response_projection` (reconstruct, pure numpy) go in `src/alive/compose/fit_role.py`, matching spec §7.1 which places `build_response_projection` there, so the stub and (later) GEARS/CPA workers import the projection contract from one module.
2. **`build_response_projection` signature is extended** from the §7.1 sketch `(response_space, *, gene_order)` to `(response_space, *, gene_order, control_mean, raw_data_sha256)`, because the §2.2 block requires the z-space `control_mean` (which is `None` on a verified `ResponseSpace`) and `raw_data_sha256`. It calls `verify_response_artifact` internally to obtain validated arrays + the combined `response_artifact_sha256`.
3. **A2's `phase2a` change is TWO focused pieces (both required by spec §7.2):** (a) `build_subprocess_fit_payload` emits `schema_version:2`, attaches both blocks, and enforces cross-source digest equality (migrated in **Task 4**, atomic with the validator flip) plus the independent `response_artifact_sha256`↔`response_space_checksum` binding (**Task 6**); and (b) `run_phase2a` calls each subprocess adapter **once with the combined double∪single pair union** and splits the result by role — honoring the §2.5 single-fit rule and §10 completion criterion (Task 8). In-process `fitted_models` (`predict_eps`, no re-fit) are unchanged and may still be evaluated per-role. **Deferred to later sub-projects (NOT A2):** the durable final-ledger + development seed-variability (sub-project **D**), and the production driver that assembles real raw/split/gene identity + approved artifacts root (sub-project **C**, spec §10.1). So A2 rewires the subprocess *invocation cardinality* but not the ledger/driver.
4. **Reference stub strategy (spec §1.2, §5, §7.2):** the v2 stub reads + validates the fit-role `.h5ad`, loads its **`combo_calibration`** cells (non-sealed, present in the artifact), treats their raw counts as the per-pair native full-gene prediction, declares `prediction_representation = "cell_raw_counts"`, applies the §2.3 operator, and returns δ̂ + a real manifest. This yields observable non-zero δ̂ and exercises the whole operator path — it is a **protocol reference, not a baseline** (its numbers are not scientific claims).

---

## File Structure

- `src/alive/compose/fit_role.py` — **first harden** A1 validation in Task 0, then add `build_response_projection`, `apply_response_projection`, `_normalize_log1p_full`.
- `src/alive/compose/response.py` — **add** `bind_response_source`. (existing fitting/projection unchanged.)
- `src/alive/compose/baseline_subprocess.py` — **modify** `_SCHEMA_VERSION`, `_REQUIRED_KEYS`, `_validate_payload`, `write_predictions`, `read_predictions`, `SubprocessBaselineBackend.predict`, `provenance_manifest`; **add** `_validate_response_projection`, `_validate_fit_role_block`, `_validate_execution_manifest`, `_float_hex`, `_float_hex_equal`, `EXECUTION_MANIFEST_KEYS`, `PREDICTION_REPRESENTATIONS`.
- `src/alive/compose/config2.py`, `configs/compose_k562_v1_phase2.yaml` — register the expected native prediction representation per GEARS/CPA method and require a bias-report digest for pseudobulk.
- `src/alive/compose/phase2a.py` — **migrate** `build_subprocess_fit_payload` → v2 emission (Task 4, atomic with the validator flip) then **bind** it to `inputs.response_space_checksum` (Task 6); **modify** `_predict_role` + `run_phase2a` and **add** `_predict_combined_adapters` (Task 8).
- `scripts/baselines/stub_worker.py` — **rewrite** to the v2 operator path (Task 5 envelope shell → Task 7 operator).
- `tests/alive/compose/test_fit_role.py` — **add** projection unit + known-answer tests.
- `tests/alive/compose/test_response.py` — **add** `bind_response_source` tests.
- `tests/alive/compose/test_baseline_subprocess.py` — **migrate** payload/prediction helpers to v2; **add** schema + envelope + leakage tests (Task 4/5); **remove** the two additive predict-through-adapter tests superseded by the integration test (Task 7).
- `tests/alive/compose/test_phase2a.py` — **migrate** `_subprocess_adapters` (real response space + fit-role artifact + `tmp_path`, Task 4; backend fields, Task 5); **add** the v2-consistency test (Task 4), the response-artifact divergence test (Task 6), and the combined-invocation test (Task 8).
- `tests/alive/compose/test_baseline_failclosed.py` — **update** the `SubprocessBaselineBackend(...)` construction (Task 5) for the new required keyword-only fields.
- `tests/alive/compose/test_payload_v2_integration.py` — **new** integration test (fixture builder + combined request through `SubprocessBaselineBackend`).

Tasks are **sequential** (later tasks import earlier symbols). BASE for Task 0 = current `main` HEAD (`62a2bd4`). Each task ends with `uv run pytest tests/alive/compose -q` green. Task 1 cannot start until Task 0's two independent-review reproductions reject.

### Fixture contract (Tasks 6, 7, 8 — the synthetic Norman-shaped fixture)

Several tasks build a synthetic fit-role `.h5ad` and a matching payload. To keep `validate_fit_role_artifact` + `apply_response_projection` + the payload validator mutually consistent, every fixture MUST satisfy:

- The artifact's `var_names` (full gene universe, e.g. `["G0"..."G7"]`) **is** the `gene_order` passed to `build_response_projection` and `bind_response_source`; all three `gene_order_sha256` values are therefore equal.
- The `ResponseSpace` is fit on the artifact's `control` + `singles` rows (indices derived from `obs.role`), and the z-space `control_mean` = `space.project(X, control_idx).mean(axis=0)`.
- The payload's `calibration_pair_ids` **==** the artifact's `combo_calibration` pairs (canonical order), and `single_gene_ids`/`delta_by_gene` cover the pair genes.
- Integration fixtures contain at least two calibration groups whose projected means are deliberately distinct, so a shared-delta or swapped pair mapping cannot pass accidentally.
- `raw_data_sha256` is one shared string across the artifact block, the projection block, and `bind_response_source`.
- The artifact is written under an approved root inside `tmp_path` (so `validate_fit_role_artifact`'s path policy passes), and `tmp_path` is threaded into `_subprocess_adapters(inputs, store, tmp_path)`.
- Requested `pair_ids` for the sealed double/single are NOT `combo_calibration` pairs (they are sealed IDs predicted from the fitted checkpoint; their cells are absent from the artifact).
- The fixture supplies `approved_artifacts_root=tmp_path` to the backend out-of-band; the worker never derives the root from the artifact path.
- The fixture's expected execution identity (representation, adapter/config/resource/environment-lock digests) is supplied to the backend independently of the worker output.

---

### Task 0: blocking A1 validator hardening

**Files:**
- Modify: `src/alive/compose/fit_role.py`
- Test: `tests/alive/compose/test_fit_role.py`

**Why this is part of the A2 plan:** A2's worker treats `validate_fit_role_artifact` as its exact pre-fit guard. The merged A1 implementation currently permits (a) a sealed combo token mislabeled as `singles`, because pair checks run only for `combo_calibration`, and (b) a `FitRoleArtifactSpec` whose raw/split/eligibility lineage fields disagree with `uns.provenance`. A2 cannot safely build on that behavior.

- [ ] **Step 1: preserve the two independent-review reproductions as failing tests**

Add tests that construct self-consistent artifacts/specs and assert rejection:

1. `obs.perturbation="AAA_BBB"`, `obs.role="singles"`, with `("AAA", "BBB")` in `sealed_pair_ids`.
2. Spec `raw_data_sha256`, `pair_manifest_sha256`, or `eligibility_hash` differs from the corresponding `uns.provenance` field while file/content digests otherwise match.
3. Duplicate/empty `source_row_id`, role-count mismatch, and `uns.provenance` row/gene digest mismatch.

- [ ] **Step 2: enforce role↔token semantics for every row**

The validator must classify every perturbation token before role-specific membership checks:

- control token → role must be `control`;
- single-gene token → role must be `singles`;
- combo token → role must be `combo_calibration`, canonical, present in the calibration set, and absent from the sealed set;
- an unregistered or malformed combo fails closed regardless of its declared role.

Do not gate sealed-pair parsing solely on `role == "combo_calibration"`.

- [ ] **Step 3: bind the trusted spec to artifact provenance and shape**

After reading the artifact, compare all independently trusted fields exactly:

```python
for key in ("raw_data_sha256", "pair_manifest_sha256", "eligibility_hash"):
    if str(adata.uns["provenance"][key]) != str(getattr(spec, key)):
        raise FitRoleArtifactError(f"{key} differs between spec and artifact provenance")
if str(adata.uns["provenance"]["row_identity_sha256"]) != spec.row_identity_sha256:
    raise FitRoleArtifactError("provenance row_identity_sha256 mismatch")
if str(adata.uns["provenance"]["gene_order_sha256"]) != spec.gene_order_sha256:
    raise FitRoleArtifactError("provenance gene_order_sha256 mismatch")
if str(adata.uns["content_manifest_sha256"]) != spec.content_manifest_sha256:
    raise FitRoleArtifactError("stored content_manifest_sha256 differs from spec")
if adata.n_obs != spec.n_cells or adata.n_vars != spec.n_genes:
    raise FitRoleArtifactError("artifact shape differs from spec")
if role_counts != spec.role_counts:
    raise FitRoleArtifactError("artifact role_counts differ from spec")
```

Require non-empty unique `source_row_id` and exact canonical perturbation tokens before recomputing row/content digests.

- [ ] **Step 4: verify the regressions and full suite**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider tests/alive/compose/test_fit_role.py -q
PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider tests/alive/compose -q
```

Expected: both former bypasses reject with `FitRoleArtifactError`; the full compose suite passes.

- [ ] **Step 5: commit**

```bash
git add src/alive/compose/fit_role.py tests/alive/compose/test_fit_role.py
git commit -m "fix(compose): close fit-role role and lineage validation bypasses (A2 prerequisite)"
```

---

### Task 1: `build_response_projection` — serialize the ResponseSpace operator

**Files:**
- Modify: `src/alive/compose/fit_role.py`
- Test: `tests/alive/compose/test_fit_role.py`

**Interfaces:**
- Consumes: `alive.compose.response.ResponseSpace`, `verify_response_artifact`, `RESPONSE_TRANSFORM`; A1's `canonical_gene_order_sha256`, `_check_gene_ids`, `FitRoleArtifactError`.
- Produces: `build_response_projection(response_space, *, gene_order, control_mean, raw_data_sha256) -> dict` returning the spec §2.2 `response_projection` block.

- [ ] **Step 1: Write the failing test**

Add to `tests/alive/compose/test_fit_role.py`:

```python
import numpy as np
from scipy import sparse

from alive.compose.fit_role import build_response_projection
from alive.compose.response import fit_response_space


def _toy_space_and_counts(seed: int = 0):
    rng = np.random.default_rng(seed)
    # 20 control + 12 single cells, 8 genes, integer counts, positive library
    counts = rng.integers(1, 40, size=(32, 8)).astype(np.float64)
    X = sparse.csr_matrix(counts)
    control_idx = np.arange(0, 20)
    single_idx = np.arange(20, 32)
    space = fit_response_space(
        X, control_idx=control_idx, eligible_single_idx=single_idx,
        n_hvg=5, pca_dim=3, seed=1,
    )
    control_mean = space.project(X, control_idx).mean(axis=0)  # z-space control centroid
    gene_order = [f"G{i}" for i in range(8)]
    return space, X, control_idx, control_mean, gene_order


def test_build_response_projection_block_shape_and_fields():
    space, X, _, control_mean, gene_order = _toy_space_and_counts()
    block = build_response_projection(
        space, gene_order=gene_order, control_mean=control_mean,
        raw_data_sha256="rawdeadbeef",
    )
    assert set(block) == {
        "response_artifact_sha256", "raw_data_sha256", "gene_order_sha256",
        "hvg_gene_ids", "transform", "median_library", "pca_mean",
        "pca_components", "control_mean", "delta_convention",
    }
    assert block["transform"] == ["normalize_total_median", "log1p"]
    assert block["delta_convention"] == "z_minus_control_mean"
    assert block["raw_data_sha256"] == "rawdeadbeef"
    # hvg_gene_ids maps hvg_idx onto gene_order, order preserved
    assert block["hvg_gene_ids"] == [gene_order[i] for i in space.hvg_idx]
    assert len(block["pca_mean"]) == space.n_hvg
    assert np.asarray(block["pca_components"]).shape == (space.pca_dim, space.n_hvg)
    assert len(block["control_mean"]) == space.pca_dim
    np.testing.assert_allclose(block["control_mean"], control_mean)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_fit_role.py::test_build_response_projection_block_shape_and_fields -q`
Expected: FAIL — `ImportError: cannot import name 'build_response_projection'`.

- [ ] **Step 3: Write minimal implementation**

At the top of `src/alive/compose/fit_role.py`, extend the response import (A1 imports only `alive.provenance`):

```python
from alive.compose.response import RESPONSE_TRANSFORM, ResponseSpace, verify_response_artifact
```

Append to `src/alive/compose/fit_role.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/alive/compose/test_fit_role.py::test_build_response_projection_block_shape_and_fields -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/fit_role.py tests/alive/compose/test_fit_role.py
git commit -m "feat(compose): serialize ResponseSpace into response_projection block (A2 task 1)"
```

---

### Task 2: `apply_response_projection` — worker-side operator + known-answer

**Files:**
- Modify: `src/alive/compose/fit_role.py`
- Test: `tests/alive/compose/test_fit_role.py`

**Interfaces:**
- Consumes: the §2.2 block from Task 1; `ResponseSpace.project` as the ground truth.
- Produces: `apply_response_projection(block, x_native, gene_order, *, representation) -> np.ndarray` returning per-row z-coordinates, shape `(n_rows, pca_dim)`; module constant `PREDICTION_REPRESENTATIONS`.

- [ ] **Step 1: Write the failing test**

Add to `tests/alive/compose/test_fit_role.py`:

```python
from alive.compose.fit_role import apply_response_projection


def test_operator_matches_responsespace_project_raw_counts():
    space, X, control_idx, control_mean, gene_order = _toy_space_and_counts(seed=3)
    block = build_response_projection(
        space, gene_order=gene_order, control_mean=control_mean, raw_data_sha256="r",
    )
    dense = np.asarray(X.todense(), dtype=np.float64)
    # single-row round trip == ResponseSpace.project on the same row
    for i in (0, 5, 25):
        z = apply_response_projection(
            block, dense[[i]], gene_order, representation="cell_raw_counts",
        )
        np.testing.assert_allclose(z[0], space.project(X, np.array([i]))[0], rtol=0, atol=1e-9)
    # population mean matches too
    idx = np.arange(20, 32)
    z_mean = apply_response_projection(
        block, dense[idx], gene_order, representation="cell_raw_counts",
    ).mean(axis=0)
    np.testing.assert_allclose(z_mean, space.project(X, idx).mean(axis=0), atol=1e-9)


def test_pseudobulk_is_a_distinct_nonlinear_path():
    space, X, control_idx, control_mean, gene_order = _toy_space_and_counts(seed=4)
    block = build_response_projection(
        space, gene_order=gene_order, control_mean=control_mean, raw_data_sha256="r",
    )
    dense = np.asarray(X.todense(), dtype=np.float64)
    idx = np.arange(20, 32)
    mean_of_project = apply_response_projection(
        block, dense[idx], gene_order, representation="cell_raw_counts",
    ).mean(axis=0)
    pseudobulk = dense[idx].mean(axis=0, keepdims=True)
    project_of_mean = apply_response_projection(
        block, pseudobulk, gene_order, representation="raw_pseudobulk_approximation",
    )[0]
    # normalize/log1p nonlinearity => the two differ (guards against silent swap)
    assert not np.allclose(mean_of_project, project_of_mean, atol=1e-6)


def test_cell_log_normalized_skips_the_raw_transform():
    space, X, control_idx, control_mean, gene_order = _toy_space_and_counts(seed=5)
    block = build_response_projection(
        space, gene_order=gene_order, control_mean=control_mean, raw_data_sha256="r",
    )
    dense = np.asarray(X.todense(), dtype=np.float64)
    i = 7
    # pre-apply the frozen normalize+log1p, then feed as log-normalized
    lib = dense[i].sum()
    normed = np.log1p(dense[i] * (block["median_library"] / lib))[None, :]
    z_log = apply_response_projection(
        block, normed, gene_order, representation="cell_log_normalized",
    )
    z_raw = apply_response_projection(
        block, dense[[i]], gene_order, representation="cell_raw_counts",
    )
    np.testing.assert_allclose(z_log[0], z_raw[0], atol=1e-9)


def test_operator_rejects_gene_order_mismatch():
    space, X, control_idx, control_mean, gene_order = _toy_space_and_counts(seed=6)
    block = build_response_projection(
        space, gene_order=gene_order, control_mean=control_mean, raw_data_sha256="r",
    )
    dense = np.asarray(X.todense(), dtype=np.float64)
    with pytest.raises(FitRoleArtifactError):
        apply_response_projection(
            block, dense[[0]], [f"X{i}" for i in range(8)],
            representation="cell_raw_counts",
        )


def test_operator_rejects_nonfinite_negative_and_scale_mismatch_inputs():
    space, X, _, control_mean, gene_order = _toy_space_and_counts(seed=7)
    block = build_response_projection(
        space, gene_order=gene_order, control_mean=control_mean, raw_data_sha256="r",
    )
    dense = np.asarray(X.todense(), dtype=np.float64)
    bad = dense[[0]].copy()
    bad[0, 0] = -1.0
    with pytest.raises(FitRoleArtifactError):
        apply_response_projection(block, bad, gene_order, representation="cell_raw_counts")
    bad[0, 0] = np.nan
    with pytest.raises(FitRoleArtifactError):
        apply_response_projection(block, bad, gene_order, representation="cell_log_normalized")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_fit_role.py -k operator -q`
Expected: FAIL — `ImportError: cannot import name 'apply_response_projection'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/alive/compose/fit_role.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/alive/compose/test_fit_role.py -k "operator or pseudobulk or log_normalized" -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/fit_role.py tests/alive/compose/test_fit_role.py
git commit -m "feat(compose): pure-numpy response operator + known-answer vs ResponseSpace.project (A2 task 2)"
```

---

### Task 3: `bind_response_source` — source digests on the response artifact

**Files:**
- Modify: `src/alive/compose/response.py`
- Test: `tests/alive/compose/test_response.py`

**Interfaces:**
- Consumes: `alive.provenance.sha256_json`.
- Produces: `bind_response_source(*, gene_order, raw_data_sha256) -> dict` returning `{"gene_order_sha256": <bare hex>, "raw_data_sha256": <str>}`, the digests phase2a enforces equal across the fit-role artifact and the projection block (spec §7.2).

- [ ] **Step 1: Write the failing test**

Add to `tests/alive/compose/test_response.py`:

```python
from alive.compose.response import bind_response_source
from alive.provenance import sha256_json


def test_bind_response_source_matches_canonical_gene_digest():
    genes = ["G0", "G1", "G2"]
    bound = bind_response_source(gene_order=genes, raw_data_sha256="rawbeef")
    assert bound == {
        "gene_order_sha256": sha256_json(["G0", "G1", "G2"]),
        "raw_data_sha256": "rawbeef",
    }


def test_bind_response_source_rejects_empty_or_duplicate_genes():
    import pytest

    with pytest.raises(ValueError):
        bind_response_source(gene_order=[], raw_data_sha256="r")
    with pytest.raises(ValueError):
        bind_response_source(gene_order=["G0", "G0"], raw_data_sha256="r")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_response.py -k bind_response_source -q`
Expected: FAIL — `ImportError: cannot import name 'bind_response_source'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/alive/compose/response.py`:

```python
def bind_response_source(
    *,
    gene_order: "Sequence[str]",
    raw_data_sha256: str,
) -> dict:
    """Bind the response artifact to its canonical gene order and raw-data digest.

    Phase-2a/2b enforce that these digests equal the fit-role artifact's and the
    projection block's, so the response space, the cell-level fit data, and the
    outcome source share one raw-data SHA and one gene order (spec §7.2, §2.2).

    Parameters
    ----------
    gene_order : sequence of str
        Canonical full gene-ID order the response space was fit against. Must be
        non-empty and unique.
    raw_data_sha256 : str
        Exact raw-data digest from the data card / RunSpec / ledger.

    Returns
    -------
    dict
        ``{"gene_order_sha256": <bare hex>, "raw_data_sha256": <str>}``.

    Raises
    ------
    ValueError
        If ``gene_order`` is empty or contains duplicate / empty IDs.
    """
    genes = [str(g) for g in gene_order]
    if not genes:
        raise ValueError("gene_order must be non-empty")
    if any(g == "" for g in genes):
        raise ValueError("gene_order must not contain empty IDs")
    if len(set(genes)) != len(genes):
        raise ValueError("gene_order must be unique")
    return {
        "gene_order_sha256": sha256_json(genes),
        "raw_data_sha256": str(raw_data_sha256),
    }
```

Add `Sequence` to the `collections.abc` import near the top of `response.py` (the module currently imports from `dataclasses`; add `from collections.abc import Sequence` with the other stdlib imports).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/alive/compose/test_response.py -k bind_response_source -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/response.py tests/alive/compose/test_response.py
git commit -m "feat(compose): bind response artifact to gene-order + raw-data digest (A2 task 3)"
```

---

### Task 4: payload-v2 schema — two blocks + cross-source equality

**Files:**
- Modify: `src/alive/compose/baseline_subprocess.py`
- Test: `tests/alive/compose/test_baseline_subprocess.py`

**Interfaces:**
- Consumes: `fit_role.PREDICTION_REPRESENTATIONS`.
- Produces: `_SCHEMA_VERSION == 2`; `_REQUIRED_KEYS` includes `fit_role_artifact`, `response_projection`; `_validate_payload(payload, *, expected_response_artifact_sha256=None)` validates both blocks + cross-block equality and, when supplied by the controller, exact equality to the independently verified response artifact; helpers `_float_hex`, `_float_hex_equal`, `_validate_fit_role_block`, `_validate_response_projection`, `_is_bare_sha256`, `_is_file_sha256`. Prediction format is **unchanged** in this task (still `{schema_version, pairs}`) — the envelope migration is Task 5.

**Note for the implementer:** `_validate_payload` still enforces exact key-set equality, so the `_payload()` test helper must be migrated to v2 (add both blocks) in this task or every subprocess test fails. Do it in Step 1's helper. The blocks are structurally validated only — **no file existence check here** (the worker validates the `.h5ad` at fit time, Task 7).

- [ ] **Step 1: Write the failing test** (migrate the helper + add schema tests)

Replace `_payload()` in `tests/alive/compose/test_baseline_subprocess.py` and add tests:

```python
from alive.provenance import sha256_json

_GENES = ["A", "B", "C"]
_GENE_ORDER_SHA = sha256_json(_GENES)


def _fit_role_block() -> dict:
    return {
        "format": "anndata_h5ad",
        "artifact_schema_version": 1,
        "path": "/approved/artifacts/fit_role.h5ad",
        "sha256": "sha256:" + "0" * 64,
        "content_manifest_sha256": "1" * 64,
        "raw_data_sha256": "raw123",
        "pair_manifest_sha256": "pm123",
        "eligibility_hash": "elig123",
        "row_identity_sha256": "2" * 64,
        "role_obs_key": "role",
        "perturbation_obs_key": "perturbation",
        "allowed_obs_roles": ["control", "singles", "combo_calibration"],
        "gene_order_sha256": _GENE_ORDER_SHA,
        "n_cells": 30,
        "n_genes": 3,
        "role_counts": {"control": 20, "singles": 6, "combo_calibration": 4},
        "counts_location": "X",
    }


def _response_projection_block(pca_components, control_mean) -> dict:
    return {
        "response_artifact_sha256": "3" * 64,
        "raw_data_sha256": "raw123",              # == fit_role_artifact.raw_data_sha256
        "gene_order_sha256": _GENE_ORDER_SHA,     # == fit_role_artifact.gene_order_sha256
        "hvg_gene_ids": ["A", "B"],
        "transform": ["normalize_total_median", "log1p"],
        "median_library": 1000.0,
        "pca_mean": [0.0, 0.0],
        "pca_components": pca_components,          # == payload["pca_components"]
        "control_mean": control_mean,             # == payload["control_mean"]
        "delta_convention": "z_minus_control_mean",
    }


def _payload() -> dict:
    pca_components = [[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]
    control_mean = [0.0, 0.0, 0.0]
    return {
        "schema_version": 2,
        "response_dim": 3,
        "seed": 11,
        "allowed_roles": ["combo_calibration", "singles"],
        "pair_ids": [["A", "B"], ["A", "C"]],
        "single_gene_ids": ["A", "B", "C"],
        "singles_response": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.7, 0.8, 0.9]],
        "control_mean": control_mean,
        "calibration_pair_ids": [["B", "C"]],
        "calibration_delta": [[0.5, 0.5, 0.5]],
        "pca_components": pca_components,
        "oof_folds": [0],
        "fit_role_artifact": _fit_role_block(),
        "response_projection": _response_projection_block(pca_components, control_mean),
    }


def test_v1_schema_version_rejected(tmp_path):
    p = _payload()
    p["schema_version"] = 1
    with pytest.raises(PayloadError):
        write_payload(str(tmp_path), p)


def test_projection_control_mean_divergence_rejected(tmp_path):
    p = _payload()
    p["response_projection"]["control_mean"] = [9.0, 9.0, 9.0]  # != payload control_mean
    with pytest.raises(PayloadError, match="control_mean"):
        write_payload(str(tmp_path), p)


def test_projection_raw_data_divergence_rejected(tmp_path):
    p = _payload()
    p["response_projection"]["raw_data_sha256"] = "different"
    with pytest.raises(PayloadError, match="raw_data"):
        write_payload(str(tmp_path), p)


def test_projection_bad_pca_mean_length_rejected(tmp_path):
    p = _payload()
    p["response_projection"]["pca_mean"] = [0.0, 0.0, 0.0]  # len 3 != 2 hvg
    with pytest.raises(PayloadError, match="pca_mean"):
        write_payload(str(tmp_path), p)


def test_projection_response_artifact_divergence_rejected():
    p = _payload()
    with pytest.raises(PayloadError, match="verified response artifact"):
        _validate_payload(p, expected_response_artifact_sha256="f" * 64)


def test_malformed_digest_and_role_counts_rejected(tmp_path):
    p = _payload()
    p["fit_role_artifact"]["content_manifest_sha256"] = "not-a-sha"
    with pytest.raises(PayloadError):
        write_payload(str(tmp_path), p)
    p = _payload()
    p["fit_role_artifact"]["role_counts"]["control"] += 1
    with pytest.raises(PayloadError, match="n_cells"):
        write_payload(str(tmp_path), p)


def test_fit_role_disallowed_obs_role_rejected(tmp_path):
    p = _payload()
    p["fit_role_artifact"]["allowed_obs_roles"] = ["control", "sealed_double_unseen"]
    with pytest.raises(ValueError):  # sealed-token scan or role-subset
        write_payload(str(tmp_path), p)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_baseline_subprocess.py -q`
Expected: FAIL — existing tests + new ones fail because `_validate_payload` rejects the two extra keys / `schema_version 2`.

- [ ] **Step 3: Write minimal implementation**

In `src/alive/compose/baseline_subprocess.py`:

```python
from alive.compose.fit_role import PREDICTION_REPRESENTATIONS

_SCHEMA_VERSION = 2
_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "schema_version", "response_dim", "seed", "allowed_roles", "pair_ids",
        "single_gene_ids", "singles_response", "control_mean", "calibration_pair_ids",
        "calibration_delta", "pca_components", "oof_folds",
        "fit_role_artifact", "response_projection",
    }
)

_FIT_ROLE_KEYS: frozenset[str] = frozenset({
    "format", "artifact_schema_version", "path", "sha256", "content_manifest_sha256",
    "raw_data_sha256", "pair_manifest_sha256", "eligibility_hash", "row_identity_sha256",
    "role_obs_key", "perturbation_obs_key", "allowed_obs_roles", "gene_order_sha256",
    "n_cells", "n_genes", "role_counts", "counts_location",
})
_ALLOWED_OBS_ROLES: frozenset[str] = frozenset({"control", "singles", "combo_calibration"})

_RESPONSE_PROJECTION_KEYS: frozenset[str] = frozenset({
    "response_artifact_sha256", "raw_data_sha256", "gene_order_sha256", "hvg_gene_ids",
    "transform", "median_library", "pca_mean", "pca_components", "control_mean",
    "delta_convention",
})


def _is_bare_sha256(value: object) -> bool:
    return (
        isinstance(value, str) and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


def _is_file_sha256(value: object) -> bool:
    return isinstance(value, str) and value.startswith("sha256:") and _is_bare_sha256(value[7:])


def _float_hex(arr) -> list:
    """Canonical float64 ``.hex()`` list for exact cross-block float equality."""
    flat = np.asarray(arr, dtype=np.float64).ravel(order="C")
    return [float(v).hex() for v in flat]


def _float_hex_equal(a, b) -> bool:
    aa, bb = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    return aa.shape == bb.shape and _float_hex(aa) == _float_hex(bb)


def _validate_fit_role_block(block: object) -> None:
    if not isinstance(block, dict) or set(block) != set(_FIT_ROLE_KEYS):
        raise PayloadError("fit_role_artifact has an unexpected key set")
    if block["format"] != "anndata_h5ad" or block["counts_location"] != "X":
        raise PayloadError("fit_role_artifact format/counts_location invalid")
    if block["artifact_schema_version"] != 1:
        raise PayloadError("fit_role_artifact artifact_schema_version must be 1")
    if block["role_obs_key"] != "role" or block["perturbation_obs_key"] != "perturbation":
        raise PayloadError("fit_role_artifact obs-key contract invalid")
    roles = block["allowed_obs_roles"]
    if not isinstance(roles, list) or set(roles) != _ALLOWED_OBS_ROLES or len(roles) != 3:
        raise PayloadError("fit_role_artifact allowed_obs_roles must be the exact role roster")
    if not _is_file_sha256(block["sha256"]):
        raise PayloadError("fit_role_artifact file sha must be exact sha256:<64 lowercase hex>")
    for key in ("content_manifest_sha256", "gene_order_sha256", "row_identity_sha256"):
        if not _is_bare_sha256(block[key]):
            raise PayloadError(f"fit_role_artifact {key} must be exact 64 lowercase hex")
    for key in ("raw_data_sha256", "pair_manifest_sha256", "eligibility_hash"):
        if not isinstance(block[key], str) or not block[key]:
            raise PayloadError(f"fit_role_artifact {key} must be a non-empty string")
    if any(isinstance(block[k], bool) or not isinstance(block[k], int) or block[k] < 1
           for k in ("n_cells", "n_genes")):
        raise PayloadError("fit_role_artifact n_cells/n_genes must be positive ints")
    counts = block["role_counts"]
    if not isinstance(counts, dict) or set(counts) != _ALLOWED_OBS_ROLES:
        raise PayloadError("fit_role_artifact role_counts must have the exact role roster")
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in counts.values()):
        raise PayloadError("fit_role_artifact role_counts must be non-negative ints")
    if sum(counts.values()) != block["n_cells"]:
        raise PayloadError("fit_role_artifact role_counts do not sum to n_cells")


def _validate_response_projection(
    block: object,
    payload: dict,
    response_dim: int,
    *,
    expected_response_artifact_sha256: str | None,
) -> None:
    if not isinstance(block, dict) or set(block) != set(_RESPONSE_PROJECTION_KEYS):
        raise PayloadError("response_projection has an unexpected key set")
    if block["transform"] != ["normalize_total_median", "log1p"]:
        raise PayloadError("response_projection transform is not the frozen transform")
    if block["delta_convention"] != "z_minus_control_mean":
        raise PayloadError("response_projection delta_convention invalid")
    if not _is_bare_sha256(block["response_artifact_sha256"]):
        raise PayloadError("response_projection response_artifact_sha256 must be 64 hex")
    if (
        expected_response_artifact_sha256 is not None
        and block["response_artifact_sha256"] != expected_response_artifact_sha256
    ):
        raise PayloadError("response_projection is not bound to the verified response artifact")
    if not _is_bare_sha256(block["gene_order_sha256"]):
        raise PayloadError("response_projection gene_order_sha256 must be 64 hex")
    hvg = block["hvg_gene_ids"]
    if (
        not isinstance(hvg, list) or not hvg
        or not all(isinstance(g, str) and g for g in hvg)
        or len(set(hvg)) != len(hvg)
    ):
        raise PayloadError("hvg_gene_ids must be a non-empty unique string list")
    n_hvg = len(hvg)
    pca_mean = np.asarray(block["pca_mean"], dtype=float)
    if pca_mean.shape != (n_hvg,) or not np.all(np.isfinite(pca_mean)):
        raise PayloadError("response_projection pca_mean must be a finite length-n_hvg vector")
    components = np.asarray(block["pca_components"], dtype=float)
    if components.shape != (response_dim, n_hvg) or not np.all(np.isfinite(components)):
        raise PayloadError("response_projection pca_components must be (response_dim, n_hvg)")
    control = np.asarray(block["control_mean"], dtype=float)
    if control.shape != (response_dim,) or not np.all(np.isfinite(control)):
        raise PayloadError("response_projection control_mean must be a finite response_dim vector")
    if isinstance(block["median_library"], bool) or not isinstance(
        block["median_library"], (int, float)
    ) or not np.isfinite(block["median_library"]) or block["median_library"] <= 0:
        raise PayloadError("response_projection median_library must be a positive number")
    # cross-source equality (spec §2.2)
    if not _float_hex_equal(components, payload["pca_components"]):
        raise PayloadError("response_projection pca_components diverge from payload pca_components")
    if not _float_hex_equal(control, payload["control_mean"]):
        raise PayloadError("response_projection control_mean diverge from payload control_mean")
    fit_role = payload["fit_role_artifact"]
    if block["raw_data_sha256"] != fit_role["raw_data_sha256"]:
        raise PayloadError("response_projection raw_data_sha256 diverges from fit_role_artifact")
    if block["gene_order_sha256"] != fit_role["gene_order_sha256"]:
        raise PayloadError("response_projection gene_order_sha256 diverges from fit_role_artifact")
```

Change `_validate_payload` to accept the keyword-only trusted checksum and, before it returns, add:

```python
    _validate_fit_role_block(payload["fit_role_artifact"])
    _validate_response_projection(
        payload["response_projection"], payload, response_dim,
        expected_response_artifact_sha256=expected_response_artifact_sha256,
    )
```

Also reject `set(pair_ids) & set(calibration_pair_ids) != ∅`: in A2, `pair_ids` is the combined sealed request and must be disjoint from all calibration cells present in the fit artifact. Add a negative test for this overlap.

(`response_dim` is already validated as a positive int earlier in `_validate_payload`. Keep the `expected_response_artifact_sha256` parameter defaulting to `None` here — Task 6 supplies it; Task 4 only makes the validator accept it.)

- [ ] **Step 3b: migrate the payload emitter and its test caller (same task — keeps `test_phase2a` green)**

**Why in this task:** flipping `_validate_payload` to require the v2 key set immediately breaks `build_subprocess_fit_payload`'s only caller `_subprocess_adapters` (`test_phase2a.py`), which still emits a v1 payload and fails `configure_payload`. The validator flip and the emitter flip must land together. All helpers this needs already exist (`build_response_projection` Task 1, `bind_response_source` Task 3, `FitRoleArtifactSpec.to_payload_block` Task 0/A1).

Add these imports at the top of `phase2a.py`:

```python
from alive.compose.fit_role import FitRoleArtifactSpec, build_response_projection
from alive.compose.response import bind_response_source
```

Rewrite `build_subprocess_fit_payload` in `phase2a.py` to emit v2 (the `response_artifact_sha256`↔`response_space_checksum` binding is added in Task 6 — omit it here):

```python
def build_subprocess_fit_payload(
    *,
    inputs: Phase2aInputs,
    outcome_store: DevelopmentOutcomeStore,
    response_artifact: Mapping,
    oof_folds: Sequence[int],
    fit_role_spec: "FitRoleArtifactSpec",
    gene_order: Sequence[str],
    raw_data_sha256: str,
) -> dict[str, object]:
    """Assemble the canonical payload-v2 fit-role payload for GEARS/CPA workers."""
    if set(response_artifact) != {"response_space", "control_mean"}:
        raise ValueError("response_artifact must contain exactly response_space + control_mean")
    response_space = response_artifact["response_space"]
    control_mean = np.asarray(response_artifact["control_mean"], dtype=float)
    if control_mean.shape != (inputs.response_dim,):
        raise ValueError("response artifact control_mean is not response_dim aligned")
    if len(oof_folds) != len(inputs.cal_pair_ids):
        raise ValueError("oof_folds must align one-to-one with calibration pairs")
    if outcome_store.combo_calibration_pair_ids != tuple(tuple(p) for p in inputs.cal_pair_ids):
        raise ValueError("development outcomes are not aligned with calibration pair IDs")

    projection = build_response_projection(
        response_space, gene_order=gene_order, control_mean=control_mean,
        raw_data_sha256=raw_data_sha256,
    )
    fit_role_block = fit_role_spec.to_payload_block()
    bound = bind_response_source(gene_order=gene_order, raw_data_sha256=raw_data_sha256)
    if fit_role_block["raw_data_sha256"] != bound["raw_data_sha256"]:
        raise ValueError("fit-role artifact raw_data_sha256 does not match response source")
    if fit_role_block["gene_order_sha256"] != bound["gene_order_sha256"]:
        raise ValueError("fit-role artifact gene_order_sha256 does not match response source")

    genes = tuple(sorted(inputs.delta_by_gene, key=lambda gene: gene.encode("utf-8")))
    calibration_delta = np.asarray(inputs.additive_cal, dtype=float) + np.asarray(
        outcome_store.combo_calibration_eps, dtype=float
    )
    return {
        "schema_version": 2,
        "response_dim": int(inputs.response_dim),
        "seed": int(inputs.seed),
        "allowed_roles": ["singles", "combo_calibration"],
        "pair_ids": [],
        "single_gene_ids": list(genes),
        "singles_response": [
            np.asarray(inputs.delta_by_gene[gene], dtype=float).tolist() for gene in genes
        ],
        # reuse the projection-serialized arrays so the cross-source equality holds
        "control_mean": projection["control_mean"],
        "calibration_pair_ids": [list(pair) for pair in inputs.cal_pair_ids],
        "calibration_delta": calibration_delta.tolist(),
        "pca_components": projection["pca_components"],
        "oof_folds": [int(fold) for fold in oof_folds],
        "fit_role_artifact": fit_role_block,
        "response_projection": projection,
    }
```

Update `_subprocess_adapters` in `test_phase2a.py` per the **Fixture contract**: replace the `SimpleNamespace(pca_components=…)` response artifact with a real `fit_response_space` result + z-space `control_mean`; set `inputs.response_space_checksum = verify_response_artifact(space, control_mean)[2]` (the combined checksum); write a real fit-role `.h5ad` via A1's `generate_fit_role_artifact` under `tmp_path` and get its `FitRoleArtifactSpec`; thread `tmp_path` into `_subprocess_adapters(inputs, store, tmp_path)`; and call `build_subprocess_fit_payload(..., fit_role_spec=spec, gene_order=var_names, raw_data_sha256=<shared>)`. Add the consistency test:

```python
def test_build_subprocess_payload_is_v2_with_consistent_blocks(tmp_path):
    # assemble inputs/store + a real response_space, control_mean and fit_role_spec
    # per the Fixture contract; gene_order == artifact var_names; one shared raw_data_sha256.
    payload = build_subprocess_fit_payload(
        inputs=inputs, outcome_store=store, response_artifact=response_artifact,
        oof_folds=[0] * len(inputs.cal_pair_ids), fit_role_spec=fit_role_spec,
        gene_order=gene_order, raw_data_sha256="shared_raw",
    )
    assert payload["schema_version"] == 2
    assert payload["response_projection"]["raw_data_sha256"] == payload["fit_role_artifact"]["raw_data_sha256"]
    assert payload["response_projection"]["response_artifact_sha256"] == inputs.response_space_checksum
    from alive.compose.baseline_subprocess import _validate_payload
    _validate_payload(payload, expected_response_artifact_sha256=inputs.response_space_checksum)
```

- [ ] **Step 4: Run the full compose suite to verify green**

Run: `uv run pytest tests/alive/compose -q`
Expected: PASS — migrated v1→v2 subprocess tests + new schema tests **and** `test_phase2a` (its `_subprocess_adapters` now emits a valid v2 payload). Prediction format is unchanged in this task; the stub still reads only aggregate keys.

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/baseline_subprocess.py src/alive/compose/phase2a.py tests/alive/compose/test_baseline_subprocess.py tests/alive/compose/test_phase2a.py
git commit -m "feat(compose): payload-v2 schema + emitter (atomic validator+emission flip) (A2 task 4)"
```

---

### Task 5: prediction envelope + backend unwrap + provenance binding

**Files:**
- Modify: `src/alive/compose/baseline_subprocess.py`, `scripts/baselines/stub_worker.py`, `src/alive/compose/config2.py`, `configs/compose_k562_v1_phase2.yaml`
- Test: `tests/alive/compose/test_baseline_subprocess.py`, `tests/alive/compose/test_config2.py`

**Interfaces:**
- Produces: `write_predictions(path, preds, *, execution_manifest) -> str`; `read_predictions(path) -> tuple[dict[tuple[str, str], np.ndarray], dict]`; structural `_validate_execution_manifest`; controller-side `_verify_execution_manifest`; frozen `ExecutionIdentityLock`; `EXECUTION_MANIFEST_KEYS`. `SubprocessBaselineBackend` receives `approved_artifacts_root`, `expected_response_artifact_sha256`, and `execution_identity_lock` out-of-band. `predict` unwraps the envelope, independently verifies every manifest identity plus the checkpoint sidecar, stores `self._last_execution_manifest`, and returns the predictions dict (adapter seam unchanged). `provenance_manifest` gains the verified checkpoint/prediction digests once a prediction has run.

**Note for the implementer:** `read_predictions` now returns a **tuple**; update `predict` to unpack it. The stub is updated here to a minimal envelope emitter (still additive singles path) so the e2e tests stay green — Task 7 replaces the stub body with the operator path. Migrate `test_prediction_round_trip` to pass an `execution_manifest` and expect the tuple.

- [ ] **Step 0: register the representation per method**

Extend the closed config schema and active YAML:

```yaml
baselines:
  gears:
    prediction_representation: raw_pseudobulk_approximation
    approximation_bias_report_sha256: null  # explicit activation blocker until measured
  cpa:
    prediction_representation: cell_raw_counts  # change only by approved config revision
    approximation_bias_report_sha256: null
```

`config2.py` must reject an unregistered representation. For `raw_pseudobulk_approximation`, it accepts either a bare 64-hex bias-report SHA or `null`; `null` must keep scientific activation blocked. Scientific activation requires the 64-hex report SHA. Cell-level representations reject a non-null bias-report SHA. The activation assembly converts this committed configuration into an `ExecutionIdentityLock`; a worker may not select its own representation.

- [ ] **Step 1: Write the failing test**

Update/add in `tests/alive/compose/test_baseline_subprocess.py`:

```python
def _manifest() -> dict:
    return {
        "prediction_representation": "cell_raw_counts",
        "adapter_version": "1",
        "adapter_sha256": "a" * 64,
        "expected_gene_order_sha256": _GENE_ORDER_SHA,
        "observed_gene_order_sha256": _GENE_ORDER_SHA,
        "checkpoint_sha256": "c" * 64,
        "worker_sha256": "b" * 64,
        "config_sha256": "e" * 64,
        "resource_sha256": "f" * 64,
        "environment_lock_sha256": "0" * 64,
        "fit_artifact_content_sha256": "1" * 64,
        "combined_request_sha256": "d" * 64,
        "predictions_sha256": "",  # filled by write_predictions? no — caller computes; see below
    }


def test_prediction_envelope_round_trip(tmp_path):
    preds = {("A", "B"): np.array([1.0, 2.0, 3.0]), ("A", "C"): np.array([4.0, 5.0, 6.0])}
    path = str(tmp_path / "preds")
    manifest = _manifest()
    c = write_predictions(path, preds, execution_manifest=manifest)
    back_preds, back_manifest = read_predictions(path)
    assert set(back_preds) == set(preds)
    np.testing.assert_allclose(back_preds[("A", "B")], preds[("A", "B")])
    assert back_manifest["prediction_representation"] == "cell_raw_counts"
    assert len(c) == 64


def test_prediction_envelope_bad_representation_rejected(tmp_path):
    preds = {("A", "B"): np.array([1.0, 2.0, 3.0])}
    manifest = _manifest()
    manifest["prediction_representation"] = "made_up"
    with pytest.raises(PayloadError, match="representation"):
        write_predictions(str(tmp_path / "p"), preds, execution_manifest=manifest)


@pytest.mark.parametrize(
    "field",
    [
        "combined_request_sha256", "fit_artifact_content_sha256", "worker_sha256",
        "checkpoint_sha256", "config_sha256", "resource_sha256",
        "environment_lock_sha256", "adapter_sha256",
    ],
)
def test_controller_rejects_self_consistent_but_false_manifest_identity(tmp_path, field):
    worker = tmp_path / "worker.py"
    checkpoint = tmp_path / "checkpoint.bin"
    worker.write_bytes(b"worker")
    checkpoint.write_bytes(b"checkpoint")
    requested = [("A", "B"), ("A", "C")]
    lock = ExecutionIdentityLock(
        prediction_representation="cell_raw_counts",
        adapter_version="1", adapter_sha256="a" * 64,
        config_sha256="e" * 64, resource_sha256="f" * 64,
        environment_lock_sha256="0" * 64,
    )
    manifest = _manifest()
    manifest.update(
        worker_sha256=_file_sha256_bare(str(worker)),
        checkpoint_sha256=_file_sha256_bare(str(checkpoint)),
        combined_request_sha256=_ordered_request_sha256(requested),
        # read_predictions normally verifies/fills this before controller verification;
        # this direct unit test supplies a structurally valid value so the selected
        # identity field is the first and only mismatch.
        predictions_sha256="8" * 64,
    )
    manifest[field] = "9" * 64
    with pytest.raises(PayloadError, match=field):
        _verify_execution_manifest(
            manifest, payload=_payload(), requested_pair_ids=requested,
            worker_script=str(worker), checkpoint_path=str(checkpoint), identity_lock=lock,
        )
```

Also update `test_prediction_round_trip` (rename or adapt to the envelope) and keep `test_predict_end_to_end_through_adapter` / `test_predict_is_deterministic` — they now flow through the envelope-emitting stub.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_baseline_subprocess.py -k envelope -q`
Expected: FAIL — `write_predictions() got an unexpected keyword argument 'execution_manifest'`.

- [ ] **Step 3: Write minimal implementation**

In `baseline_subprocess.py`:

Extend the existing collections import so the new annotations pass Ruff/static validation:

```python
from collections.abc import Mapping, Sequence
```

```python
EXECUTION_MANIFEST_KEYS: frozenset[str] = frozenset({
    "prediction_representation", "adapter_version", "adapter_sha256",
    "expected_gene_order_sha256", "observed_gene_order_sha256", "checkpoint_sha256",
    "worker_sha256", "config_sha256", "resource_sha256", "environment_lock_sha256",
    "fit_artifact_content_sha256", "combined_request_sha256", "predictions_sha256",
})


@dataclass(frozen=True)
class ExecutionIdentityLock:
    prediction_representation: str
    adapter_version: str
    adapter_sha256: str
    config_sha256: str
    resource_sha256: str
    environment_lock_sha256: str


def _validate_execution_manifest(manifest: object) -> None:
    if not isinstance(manifest, dict) or set(manifest) != set(EXECUTION_MANIFEST_KEYS):
        raise PayloadError("execution_manifest has an unexpected key set")
    if manifest["prediction_representation"] not in PREDICTION_REPRESENTATIONS:
        raise PayloadError("execution_manifest prediction_representation is not a registered enum")
    if manifest["expected_gene_order_sha256"] != manifest["observed_gene_order_sha256"]:
        raise PayloadError("worker observed a different gene order than expected")
    for key in EXECUTION_MANIFEST_KEYS:
        if not (isinstance(manifest[key], str) and manifest[key]):
            raise PayloadError(f"execution_manifest {key} must be a non-empty string")
    for key in (
        "adapter_sha256", "expected_gene_order_sha256", "observed_gene_order_sha256",
        "checkpoint_sha256", "worker_sha256", "fit_artifact_content_sha256",
        "combined_request_sha256", "predictions_sha256", "config_sha256",
        "resource_sha256", "environment_lock_sha256",
    ):
        if not _is_bare_sha256(manifest[key]):
            raise PayloadError(f"execution_manifest {key} must be exact 64 lowercase hex")


def _ordered_request_sha256(pair_ids: Sequence[tuple[str, str]]) -> str:
    return _sha256(_canonical_json([list(pair) for pair in pair_ids]))


def _file_sha256_bare(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_execution_manifest(
    manifest: Mapping[str, str],
    *,
    payload: Mapping[str, object],
    requested_pair_ids: Sequence[tuple[str, str]],
    worker_script: str,
    checkpoint_path: str,
    identity_lock: ExecutionIdentityLock,
) -> None:
    """Compare worker claims with controller-computed/trusted identities."""
    _validate_execution_manifest(dict(manifest))
    expected = {
        "prediction_representation": identity_lock.prediction_representation,
        "adapter_version": identity_lock.adapter_version,
        "adapter_sha256": identity_lock.adapter_sha256,
        "config_sha256": identity_lock.config_sha256,
        "resource_sha256": identity_lock.resource_sha256,
        "environment_lock_sha256": identity_lock.environment_lock_sha256,
        "expected_gene_order_sha256": payload["response_projection"]["gene_order_sha256"],
        "fit_artifact_content_sha256": payload["fit_role_artifact"][
            "content_manifest_sha256"
        ],
        "combined_request_sha256": _ordered_request_sha256(requested_pair_ids),
        "worker_sha256": _file_sha256_bare(worker_script),
        "checkpoint_sha256": _file_sha256_bare(checkpoint_path),
    }
    for key, value in expected.items():
        if manifest[key] != value:
            raise PayloadError(f"execution_manifest {key} differs from controller expectation")


def write_predictions(
    path: str,
    preds: Mapping[tuple[str, str], np.ndarray],
    *,
    execution_manifest: Mapping[str, object],
) -> str:
    pairs = [[list(p), np.asarray(v, dtype=float).tolist()] for p, v in preds.items()]
    predictions_sha256 = _sha256(_canonical_json(pairs))
    manifest = dict(execution_manifest)
    manifest["predictions_sha256"] = predictions_sha256
    _validate_execution_manifest(manifest)
    obj = {"schema_version": _SCHEMA_VERSION, "predictions": pairs, "execution_manifest": manifest}
    text = _canonical_json(obj)
    with open(path + ".json", "w", encoding="utf-8") as fh:
        fh.write(text)
    return _sha256(text)


def read_predictions(path: str) -> tuple[dict[tuple[str, str], np.ndarray], dict]:
    with open(path + ".json", encoding="utf-8") as fh:
        obj = json.load(fh)
    if set(obj) != {"schema_version", "predictions", "execution_manifest"}:
        raise PayloadError("prediction file has an unexpected key set")
    if obj.get("schema_version") != _SCHEMA_VERSION:
        raise PayloadError("prediction file has an unexpected schema_version")
    if not isinstance(obj["predictions"], list):
        raise PayloadError("predictions must be a list")
    predictions: dict[tuple[str, str], np.ndarray] = {}
    for item in obj["predictions"]:
        if not isinstance(item, list) or len(item) != 2:
            raise PayloadError("each prediction record must be [pair, vector]")
        pair, vec = item
        if (
            not isinstance(pair, list) or len(pair) != 2
            or not all(isinstance(gene, str) and gene for gene in pair)
        ):
            raise PayloadError("prediction pair IDs must be two non-empty strings")
        pair_id = (pair[0], pair[1])
        if pair_id in predictions:
            raise PayloadError(f"duplicate prediction pair {pair_id!r}")
        predictions[pair_id] = np.asarray(vec, dtype=float)
    manifest = obj["execution_manifest"]
    _validate_execution_manifest(manifest)
    recomputed = _sha256(_canonical_json(obj["predictions"]))
    if manifest["predictions_sha256"] != recomputed:
        raise PayloadError("execution_manifest predictions_sha256 does not match predictions")
    return predictions, dict(manifest)
```

Add these required, out-of-band fields to `SubprocessBaselineBackend`. **They MUST be keyword-only** — `SubprocessBaselineBackend` already has a defaulted field `seed: int = 11`, so a required (no-default) field placed after it raises `TypeError: non-default argument follows default argument` at class-definition time (breaking every import of the module). Insert a `dataclasses.KW_ONLY` sentinel so the required fields are keyword-only:

```python
from dataclasses import KW_ONLY  # add to the existing dataclasses import
...
    seed: int = 11
    _: KW_ONLY
    approved_artifacts_root: str
    expected_response_artifact_sha256: str
    execution_identity_lock: ExecutionIdentityLock
    _available: bool | None = field(default=None, init=False, repr=False)
    _payload: dict | None = field(default=None, init=False, repr=False)
    _last_execution_manifest: dict | None = field(default=None, init=False, repr=False)
```

`configure_payload` must call
`_validate_payload(candidate, expected_response_artifact_sha256=self.expected_response_artifact_sha256)`.
Before launching a worker, canonicalize `approved_artifacts_root`, require it to be an absolute existing directory,
and pass it as `--approved-root <root>`. Do not read this value from the payload or infer it from
`fit_role_artifact.path`. (The directory is validated at predict time, not at construction.)

**Update EVERY `SubprocessBaselineBackend(...)` construction site in this same task** — the fields are required, so any un-updated construction is a `TypeError` and the task ends red. The definitive list (from `grep -rn 'SubprocessBaselineBackend(' tests/`) is **six** sites in **three** files, all keyword-constructed:
- `tests/alive/compose/test_baseline_subprocess.py`: the three `test_is_available_*` constructions (lines ~91/98/108) and `_backend()` (~line 128).
- `tests/alive/compose/test_phase2a.py`: `_subprocess_adapters` (~line 176).
- `tests/alive/compose/test_baseline_failclosed.py`: `test_unavailable_backend_raises_baseline_unavailable` (~line 31).

Pass test-appropriate values: `approved_artifacts_root=str(tmp_path)` (or any literal string for availability/fail-closed constructions, which never reach predict-time root validation), `expected_response_artifact_sha256="0" * 64`, and `execution_identity_lock=ExecutionIdentityLock(prediction_representation="cell_raw_counts", adapter_version="1", adapter_sha256="a"*64, config_sha256="e"*64, resource_sha256="f"*64, environment_lock_sha256="0"*64)`. Sites that never predict (the three availability tests and the fail-closed unavailable-backend test — the adapter raises `BaselineUnavailable`/short-circuits on `is_available` before predict) only need the fields to *construct*. `test_payload_with_sealed_token_is_refused` still passes because `configure_payload` runs `_assert_no_sealed_reference` **before** `_validate_payload`, so the dummy `expected_response_artifact_sha256` is never reached. (`_backend()` needs a `tmp_path` param or a module-level temp dir.)

Update `predict` (bottom of the method) to unwrap + store:

```python
            preds, manifest = read_predictions(out)
            checkpoint_path = out + ".checkpoint"
            if os.path.islink(checkpoint_path) or not os.path.isfile(checkpoint_path):
                raise PayloadError("worker did not produce the required checkpoint sidecar")
            _verify_execution_manifest(
                manifest,
                payload=payload,
                requested_pair_ids=pair_ids,
                worker_script=self.worker_script,
                checkpoint_path=checkpoint_path,
                identity_lock=self.execution_identity_lock,
            )
            self._last_execution_manifest = manifest
            return preds
```

Add the field to the dataclass: `_last_execution_manifest: dict | None = field(default=None, init=False, repr=False)`. In `provenance_manifest`, include the complete frozen `execution_identity_lock`; after a successful controller-side verification, include the **entire** execution manifest as `{key: self._last_execution_manifest[key] for key in sorted(EXECUTION_MANIFEST_KEYS)}`. Do not retain only a digest subset: ordered request, worker/config/resource/environment and adapter identities must all enter the method lock. This makes `provenance_manifest` carry verified execution evidence once a predict has run; the actual binding into the Phase-2a method lock (spec §2.5, §10) is realized in **Task 8**, which orders the combined predict before that provenance read. Keep `provenance_manifest` valid before any predict by guarding on `None`, but scientific completion requires the post-predict form.

Rewrite `scripts/baselines/stub_worker.py` to emit the envelope (minimal, additive path retained for this task):

Task 5 must already accept the trusted-root CLI argument that the backend now always sends; Task 7 later starts
*using* it for artifact validation. Update the imports/parser in this task, not Task 7:

```python
import argparse
import hashlib
import json

import numpy as np

from alive.compose.baseline_subprocess import read_payload, write_predictions


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="work_dir", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--approved-root", required=True)
    a = ap.parse_args()
    p = read_payload(a.work_dir)
    ids = list(p["single_gene_ids"])
    singles = np.asarray(p["singles_response"], dtype=float)
    idx = {g: i for i, g in enumerate(ids)}
    dim = int(p["response_dim"])
```

The transitional additive stub does not open the artifact yet, but it must parse the argument so the Task-5
backend invocation and existing adapter e2e tests remain green. Task 7 replaces this body and uses
`a.approved_root` in `validate_fit_role_artifact`.

Continue inside `main`:

```python
    preds = {}
    for g, h in p["pair_ids"]:
        vec = singles[idx[g]] + singles[idx[h]]
        preds[(g, h)] = vec[:dim]
    fit_role = p["fit_role_artifact"]
    proj = p["response_projection"]
    checkpoint_bytes = json.dumps(
        {"stub": "additive-envelope-transition"}, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    with open(a.out + ".checkpoint", "xb") as fh:
        fh.write(checkpoint_bytes)
    manifest = {
        "prediction_representation": "cell_raw_counts",
        "adapter_version": "stub-1",
        "adapter_sha256": hashlib.sha256(b"stub-1").hexdigest(),
        "expected_gene_order_sha256": proj["gene_order_sha256"],
        "observed_gene_order_sha256": proj["gene_order_sha256"],
        "checkpoint_sha256": hashlib.sha256(checkpoint_bytes).hexdigest(),
        "worker_sha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(),
        "config_sha256": hashlib.sha256(b"stub-config").hexdigest(),
        "resource_sha256": hashlib.sha256(b"stub-resource").hexdigest(),
        "environment_lock_sha256": hashlib.sha256(b"stub-environment").hexdigest(),
        "fit_artifact_content_sha256": fit_role["content_manifest_sha256"],
        "combined_request_sha256": hashlib.sha256(
            json.dumps(p["pair_ids"], sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "predictions_sha256": "",  # write_predictions fills this
    }
    write_predictions(a.out, preds, execution_manifest=manifest)
```

- [ ] **Step 4: Run the FULL compose suite to verify it passes**

Run: `uv run pytest tests/alive/compose -q`
Expected: PASS — envelope round-trip, rejection, the migrated e2e/deterministic predict tests, **and** all six updated `SubprocessBaselineBackend(...)` construction sites across `test_baseline_subprocess.py`, `test_phase2a.py`, `test_baseline_failclosed.py` (the required keyword-only fields don't break construction anywhere). Running the whole compose dir — not a single file — is what catches a missed cross-file construction site.

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/baseline_subprocess.py scripts/baselines/stub_worker.py src/alive/compose/config2.py configs/compose_k562_v1_phase2.yaml tests/alive/compose/test_baseline_subprocess.py tests/alive/compose/test_config2.py tests/alive/compose/test_phase2a.py tests/alive/compose/test_baseline_failclosed.py
git commit -m "feat(compose): {predictions, execution_manifest} envelope + backend unwrap/binding (A2 task 5)"
```

---

### Task 6: bind the payload emitter to the independently verified response artifact

**Files:**
- Modify: `src/alive/compose/phase2a.py`
- Test: `tests/alive/compose/test_phase2a.py`

**Interfaces:**
- Consumes: the v2 `build_subprocess_fit_payload` already migrated in **Task 4** (blocks + cross-source equality + source binding).
- Produces: `build_subprocess_fit_payload` additionally raises `ValueError` when `projection["response_artifact_sha256"] != inputs.response_space_checksum`, closing the circular-equality gap (Global Constraint "Response artifact equality is not circular"; spec §2.2).

**Note for the implementer:** Task 4 already emits v2 and passes `_subprocess_adapters` on the consistency test. This task adds only the **independent** binding: the projection's `response_artifact_sha256` must equal `Phase2aInputs.response_space_checksum` (the separately verified response-space checksum, see `phase2a._verify_scientific_response_artifact`), not merely be self-consistent inside the payload. The `configure_payload` side of this binding (`_validate_payload(..., expected_response_artifact_sha256=self.expected_response_artifact_sha256)`) is wired in Task 5; here we enforce it at emission.

- [ ] **Step 1: Write the failing test**

Reuse the Task-4 fixture (`test_build_subprocess_payload_is_v2_with_consistent_blocks`) but with a mismatched checksum; `build_subprocess_fit_payload` must raise before returning a payload:

```python
def test_build_subprocess_payload_rejects_unverified_response_artifact(tmp_path):
    # same Fixture-contract assembly as Task 4, then corrupt the bound checksum:
    inputs = replace(inputs, response_space_checksum="f" * 64)  # != projection's combined checksum
    with pytest.raises(ValueError, match="independently verified response artifact"):
        build_subprocess_fit_payload(
            inputs=inputs, outcome_store=store, response_artifact=response_artifact,
            oof_folds=[0] * len(inputs.cal_pair_ids), fit_role_spec=fit_role_spec,
            gene_order=gene_order, raw_data_sha256="shared_raw",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_phase2a.py -k unverified_response_artifact -q`
Expected: FAIL — no guard yet; the payload is returned instead of raising.

- [ ] **Step 3: Write minimal implementation**

In `build_subprocess_fit_payload` (Task 4), immediately after the `projection = build_response_projection(...)` call, add:

```python
    if projection["response_artifact_sha256"] != inputs.response_space_checksum:
        raise ValueError("projection does not match the independently verified response artifact")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/alive/compose/test_phase2a.py -q`
Expected: PASS — the divergence test raises; the Task-4 consistency test and every other phase2a test still pass.

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/phase2a.py tests/alive/compose/test_phase2a.py
git commit -m "feat(compose): bind payload emitter to the verified response artifact checksum (A2 task 6)"
```

---

### Task 7: v2 stub worker operator path + integration test

**Files:**
- Modify: `scripts/baselines/stub_worker.py`
- Create: `tests/alive/compose/test_payload_v2_integration.py`

**Interfaces:**
- Consumes: `validate_fit_role_artifact` + `apply_response_projection` (fit_role), `SubprocessBaselineBackend`, `write_payload`/`read_payload`, A1's `generate_fit_role_artifact` (fixture).
- Produces: a stub worker that reads + validates the fit-role `.h5ad`, fits once (deterministic checkpoint), predicts native full-gene per pair from the artifact's `combo_calibration` cells, applies the §2.3 operator, and returns the envelope with real digests; an integration test that drives a combined double+single request through `SubprocessBaselineBackend` and asserts fit-once/checkpoint/manifest/role-split/projection.

**Note for the implementer:** this is the task that makes the stub non-trivial (spec §7.2 — aggregate-only additive behavior must NOT pass integration). The stub must open the `.h5ad`, so the integration test writes a **real** fit-role artifact via A1's `generate_fit_role_artifact` into an approved root under `tmp_path` and references it (path + digests) in the payload's `fit_role_artifact` block. Sealed rows are never present in the artifact (A1 guarantees this); the stub reads only `combo_calibration` cells.

- [ ] **Step 1: Write the failing test**

Create `tests/alive/compose/test_payload_v2_integration.py`. It must:
1. Build a synthetic Norman-shaped AnnData (control + singles + **at least two distinct combo_calibration pairs**, with multiple cells per pair; a small full gene universe) in `tmp_path`.
2. Run the audited extractor + `generate_fit_role_artifact` to write a real `.h5ad` + get a `FitRoleArtifactSpec`.
3. Fit a real `ResponseSpace` on control+single rows; compute the z-space `control_mean`; build the `response_projection` block; build a valid v2 payload whose `fit_role_artifact` block = `spec.to_payload_block()` (with `path` = the real artifact path) and whose aggregate `pca_components`/`control_mean` = the projection's.
4. Configure a `SubprocessBaselineBackend(name="stub", env_python=sys.executable, worker_script=<stub>, import_name="json", approved_artifacts_root=str(tmp_path), expected_response_artifact_sha256=inputs.response_space_checksum, execution_identity_lock=<fixture lock>)` with that payload and predict a **combined** request of one double + one single-unseen pair.
5. Assert:

```python
    out = adapter.predict(context, [("AAA", "BBB"), ("AAA", "CCC")], response_dim)
    assert set(out) == {("AAA", "BBB"), ("AAA", "CCC")}
    for vec in out.values():
        assert vec.shape == (response_dim,)
        assert np.all(np.isfinite(vec))
    # projection path was exercised (δ̂ is not identically zero for calibration-cell native preds)
    assert any(np.linalg.norm(v) > 1e-9 for v in out.values())
    # the manifest bound into provenance carries the checkpoint + prediction digests
    prov = backend.provenance_manifest
    assert prov["execution_manifest"]["prediction_representation"] == "cell_raw_counts"
    assert len(prov["execution_manifest"]["checkpoint_sha256"]) == 64
    # pair-to-native-row association is exercised, not one shared delta for all requests
    assert not np.array_equal(out[("AAA", "BBB")], out[("AAA", "CCC")])
```

Also add tamper assertions: mutate the artifact bytes after the payload is built and assert the worker fails (`BaselineUnavailable`) before returning predictions; separately mutate the emitted checkpoint sidecar or any controller-verifiable manifest identity and assert `PayloadError`. Add an outside-root artifact case and prove it rejects even when its file SHA/content manifest are otherwise valid.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_payload_v2_integration.py -q`
Expected: FAIL — the Task-5 stub now emits a structurally valid envelope and checkpoint sidecar but still uses the
aggregate additive path and never reads the fit-role artifact or applies the registered response operator. The Task-7
integration therefore fails its operator-path and pair-associated native-prediction assertions.

- [ ] **Step 3: Write minimal implementation**

Rewrite `scripts/baselines/stub_worker.py` to the operator path:

```python
# scripts/baselines/stub_worker.py
"""SYNTHETIC-ONLY payload-v2 reference worker (protocol reference, not a baseline).

Reads + validates the fit-role artifact, fits once (a deterministic checkpoint
over the combo_calibration cells), predicts each requested pair's native
full-gene expression as those calibration cells, applies the registered §2.3
response operator, and returns the {predictions, execution_manifest} envelope.
The real gears/cpa workers replace this under the locked envs (pod-only).
"""

from __future__ import annotations

import argparse
import hashlib
import json

import anndata as ad
import numpy as np

from alive.compose.baseline_subprocess import read_payload, write_predictions
from alive.compose.fit_role import (
    FitRoleArtifactSpec,
    apply_response_projection,
    canonical_gene_order_sha256,
    validate_fit_role_artifact,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="work_dir", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--approved-root", required=True)
    a = ap.parse_args()
    p = read_payload(a.work_dir)
    fit_role = p["fit_role_artifact"]
    proj = p["response_projection"]
    dim = int(p["response_dim"])

    # 1. re-validate the artifact exactly as the guard requires (fails closed)
    spec = FitRoleArtifactSpec(
        path=fit_role["path"], sha256=fit_role["sha256"],
        content_manifest_sha256=fit_role["content_manifest_sha256"],
        raw_data_sha256=fit_role["raw_data_sha256"],
        pair_manifest_sha256=fit_role["pair_manifest_sha256"],
        eligibility_hash=fit_role["eligibility_hash"],
        row_identity_sha256=fit_role["row_identity_sha256"],
        gene_order_sha256=fit_role["gene_order_sha256"],
        n_cells=int(fit_role["n_cells"]), n_genes=int(fit_role["n_genes"]),
        role_counts=dict(fit_role["role_counts"]),
    )
    validate_fit_role_artifact(
        fit_role["path"], spec=spec, approved_root=a.approved_root,
        calibration_pair_ids=[tuple(pr) for pr in p["calibration_pair_ids"]],
        # Requested pair identities are allowed in the request but their cells must
        # never occur in the fit artifact.
        sealed_pair_ids=[tuple(pr) for pr in p["pair_ids"]],
    )

    # 2. load the artifact; native full-gene combo_calibration cells only
    adata = ad.read_h5ad(fit_role["path"])
    gene_order = [str(v) for v in adata.var_names]
    roles = [str(r) for r in adata.obs["role"]]
    perts = [str(v) for v in adata.obs["perturbation"]]
    calibration_groups: dict[str, np.ndarray] = {}
    for token in sorted({p for p, r in zip(perts, roles) if r == "combo_calibration"}):
        idx = np.array(
            [
                i
                for i, (p, r) in enumerate(zip(perts, roles))
                if p == token and r == "combo_calibration"
            ]
        )
        calibration_groups[token] = np.asarray(adata.X[idx].todense(), dtype=np.float64)
    if not calibration_groups:
        raise ValueError("reference worker requires combo_calibration cells")

    # 3. fit once -> write-once deterministic checkpoint sidecar over the fitted bank
    checkpoint_obj = {
        "schema": "stub_calibration_bank_v1",
        "gene_order_sha256": canonical_gene_order_sha256(gene_order),
        "groups": {
            token: [[float(v).hex() for v in row] for row in matrix]
            for token, matrix in calibration_groups.items()
        },
    }
    checkpoint_bytes = json.dumps(
        checkpoint_obj, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    with open(a.out + ".checkpoint", "xb") as fh:
        fh.write(checkpoint_bytes)
    checkpoint = hashlib.sha256(checkpoint_bytes).hexdigest()

    # 4. predict combined union once. The synthetic reference deterministically maps
    # each request to one fitted calibration group, preserving pair association while
    # making no scientific baseline claim.
    control_mean = np.asarray(proj["control_mean"], dtype=np.float64)
    group_keys = sorted(calibration_groups)
    preds = {}
    for g, h in p["pair_ids"]:
        request_digest = hashlib.sha256(f"{g}\0{h}".encode("utf-8")).digest()
        token = group_keys[int.from_bytes(request_digest[:8], "big") % len(group_keys)]
        native = calibration_groups[token]
        z = apply_response_projection(proj, native, gene_order, representation="cell_raw_counts")
        preds[(g, h)] = (z.mean(axis=0) - control_mean)[:dim]

    manifest = {
        "prediction_representation": "cell_raw_counts",
        "adapter_version": "stub-2",
        "adapter_sha256": hashlib.sha256(b"stub-response-operator-v2").hexdigest(),
        "expected_gene_order_sha256": proj["gene_order_sha256"],
        "observed_gene_order_sha256": canonical_gene_order_sha256(gene_order),
        "checkpoint_sha256": checkpoint,
        "worker_sha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(),
        "config_sha256": hashlib.sha256(b"stub-config").hexdigest(),
        "resource_sha256": hashlib.sha256(b"stub-resource").hexdigest(),
        "environment_lock_sha256": hashlib.sha256(b"stub-environment").hexdigest(),
        "fit_artifact_content_sha256": fit_role["content_manifest_sha256"],
        "combined_request_sha256": hashlib.sha256(
            json.dumps([list(pr) for pr in p["pair_ids"]], separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "predictions_sha256": "",
    }
    write_predictions(a.out, preds, execution_manifest=manifest)


if __name__ == "__main__":
    main()
```

The stub deliberately produces δ̂ from the calibration cells' native projection, so `expected == observed` gene order, the operator runs, and δ̂ ≠ 0.

- [ ] **Step 4: Migrate the two now-broken additive predict tests**

Rewriting the shared `stub_worker.py` to the operator path breaks two tests in `tests/alive/compose/test_baseline_subprocess.py` that drive the *same* stub with the fake `_payload()` path and assert the additive sum `[0.5, 0.7, 0.9]`:
`test_predict_end_to_end_through_adapter` and `test_predict_is_deterministic`. Those additive semantics no longer exist (the v2 stub is operator-based and requires a real `.h5ad`), and the adapter-through-backend e2e is now covered by `test_payload_v2_integration.py`. **Delete both tests** from `test_baseline_subprocess.py`. **Keep** `test_payload_with_sealed_token_is_refused` — it only calls `configure_payload` (which validates the payload without running the worker) and remains valid. If `_context`/`_backend`/`_STUB` become unused after the deletion, remove them; if the retained refusal test still uses `_backend`/`_STUB`, leave those in place.

- [ ] **Step 5: Run the integration + subprocess tests**

Run: `uv run pytest tests/alive/compose/test_payload_v2_integration.py tests/alive/compose/test_baseline_subprocess.py -q`
Expected: PASS — combined request predicts both pairs, δ̂ non-trivial, manifest carries a real per-fit checkpoint, tamper is caught before prediction; the two additive tests are gone and the sealed-token refusal test still passes.

- [ ] **Step 6: Run the full compose suite + ruff, then commit**

Run: `uv run pytest tests/alive/compose -q && uv run ruff check src/alive/compose scripts/baselines tests/alive/compose && uv run ruff format --check src/alive/compose scripts/baselines tests/alive/compose`
Expected: all green.

```bash
git add scripts/baselines/stub_worker.py tests/alive/compose/test_payload_v2_integration.py tests/alive/compose/test_baseline_subprocess.py
git commit -m "feat(compose): v2 reference stub operator path + payload-v2 integration test (A2 task 7)"
```

---

### Task 8: single combined subprocess invocation in `run_phase2a` (§2.5)

**Files:**
- Modify: `src/alive/compose/phase2a.py`
- Test: `tests/alive/compose/test_phase2a.py`

**Interfaces:**
- Produces: `_combined_pair_union(double_ids, single_ids) -> list[tuple[str, str]]`; `_baseline_context(inputs) -> BaselineTrainingContext`; `_predict_combined_adapters(inputs, combined_pair_ids, baseline_adapters) -> dict[str, dict[tuple[str, str], np.ndarray]]`. `_predict_role` gains a keyword `adapter_predictions: Mapping | None = None`; `run_phase2a` computes the union once, calls `_predict_combined_adapters` once, and passes the result to both `_predict_role` calls.

**Why:** spec §2.5/§7.2/§10 require each subprocess worker to fit **once** and predict the combined pair union once — `SubprocessBaselineBackend.predict` runs a fresh worker (fit + predict) per call, so calling it once per role (as `run_phase2a` does today at `phase2a.py:1256-1271`) re-fits GEARS/CPA twice. In-process `fitted_models` use `predict_eps` (no re-fit) and are unaffected; only the subprocess-adapter branch is rerouted.

- [ ] **Step 1: Write the failing test**

Add to `tests/alive/compose/test_phase2a.py` (reuse the existing minimal-`Phase2aInputs` construction; `Z`/`mean` can be zeros of the right shape):

```python
from alive.compose.phase2a import (
    _combined_pair_union,
    _predict_combined_adapters,
    _predict_role,
)


class _SpyAdapter:
    """Duck-typed baseline adapter that records each predict() call."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple] = []

    def predict(self, context, pair_ids, response_dim):
        self.calls.append(tuple(tuple(p) for p in pair_ids))
        return {(g, h): np.full(response_dim, len(g + h), dtype=float) for g, h in pair_ids}


def test_subprocess_adapter_fits_once_for_combined_union(minimal_inputs):
    inputs = minimal_inputs  # sealed_double_pair_ids + sealed_single_pair_ids disjoint, non-empty
    spy = _SpyAdapter("gears")
    adapters = {"gears": spy}
    combined = _combined_pair_union(inputs.sealed_double_pair_ids, inputs.sealed_single_pair_ids)
    adapter_preds = _predict_combined_adapters(inputs, combined, adapters)
    assert len(spy.calls) == 1                              # fit-once
    assert spy.calls[0] == tuple(combined)                 # combined union, once
    Z = np.zeros((1, inputs.response_dim))
    mean = np.zeros(inputs.response_dim)
    double = _predict_role(
        inputs, inputs.sealed_double_pair_ids, {}, Z, mean, adapters,
        adapter_predictions=adapter_preds,
    )
    single = _predict_role(
        inputs, inputs.sealed_single_pair_ids, {}, Z, mean, adapters,
        adapter_predictions=adapter_preds,
    )
    assert len(spy.calls) == 1                              # NOT re-invoked during role split
    assert set(double["gears"]) == {tuple(p) for p in inputs.sealed_double_pair_ids}
    assert set(single["gears"]) == {tuple(p) for p in inputs.sealed_single_pair_ids}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_phase2a.py -k combined_union -q`
Expected: FAIL — `ImportError: cannot import name '_combined_pair_union'` / `_predict_role` has no `adapter_predictions` kwarg.

- [ ] **Step 3: Write minimal implementation**

In `phase2a.py`, extract the adapter context and add the two helpers:

```python
def _baseline_context(inputs: Phase2aInputs) -> BaselineTrainingContext:
    """The frozen development-role context handed to every subprocess adapter."""
    return BaselineTrainingContext(
        allowed_roles=frozenset({"singles", "combo_calibration"}),
        pair_manifest_checksum=inputs.manifest_checksum,
        response_space_checksum=inputs.response_space_checksum,
        training_pair_ids=tuple(tuple(p) for p in inputs.cal_pair_ids),
        single_gene_ids=tuple(
            sorted(inputs.delta_by_gene, key=lambda gene: str(gene).encode("utf-8"))
        ),
    )


def _combined_pair_union(
    double_ids: Sequence[tuple[str, str]],
    single_ids: Sequence[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Ordered de-duplicated double∪single request (doubles first) for a single fit."""
    union: list[tuple[str, str]] = []
    for p in (*double_ids, *single_ids):
        pair = (p[0], p[1])
        if pair not in union:
            union.append(pair)
    return union


def _predict_combined_adapters(
    inputs: Phase2aInputs,
    combined_pair_ids: Sequence[tuple[str, str]],
    baseline_adapters: Mapping[str, object],
) -> dict[str, dict[tuple[str, str], np.ndarray]]:
    """Invoke every subprocess adapter EXACTLY once on the combined pair union.

    Honors the single-fit / single-checkpoint / combined-request rule (spec §2.5):
    each worker fits once and predicts the whole union; ``_predict_role`` then
    splits the cached result per role without re-invoking the worker.
    """
    context = _baseline_context(inputs)
    return {
        name: adapter.predict(context, list(combined_pair_ids), inputs.response_dim)
        for name, adapter in baseline_adapters.items()
    }
```

Change the `_predict_role` signature to add `adapter_predictions` and reroute its adapter branch:

```python
def _predict_role(
    inputs: Phase2aInputs,
    pair_ids: Sequence[tuple[str, str]],
    fitted_models: Mapping[str, object],
    selected_Z: np.ndarray,
    perturbation_mean_prediction: np.ndarray,
    baseline_adapters: Mapping[str, BaselineAdapter] | None = None,
    *,
    adapter_predictions: Mapping[str, Mapping[tuple[str, str], np.ndarray]] | None = None,
) -> dict[str, dict[tuple[str, str], np.ndarray]]:
    ...
    # (learned models / additive / no_change / perturbation_mean unchanged)
    if baseline_adapters:
        if adapter_predictions is None:
            context = _baseline_context(inputs)
            for name, adapter in baseline_adapters.items():
                out[name] = adapter.predict(context, list(pair_ids), inputs.response_dim)
        else:
            for name in baseline_adapters:
                combined = adapter_predictions[name]
                out[name] = {
                    (g, h): np.asarray(combined[(g, h)], dtype=float) for g, h in pair_ids
                }
    return out
```

Replace the inline context block that previously lived in `_predict_role` with a call to `_baseline_context(inputs)` (the extraction above).

Then edit `run_phase2a` so the combined subprocess invocation happens **before** the method-lock checksum is computed. Currently `run_phase2a` reads each adapter's `provenance_manifest` (`phase2a.py:1243-1244`) into `model_artifact_checksums` and folds it into `effective_model_checksum` (`phase2a.py:1245`), and only *then* calls `_predict_role` (`phase2a.py:1256-1271`). Because `SubprocessBaselineBackend.provenance_manifest` only carries the `execution_manifest` (checkpoint + prediction digests) **after** a predict has run (Task 5), the checkpoint/prediction digests must be produced before that read to bind into the method lock (spec §2.5/§10). So insert the combined invocation immediately **before** the adapter `provenance_manifest` loop at `phase2a.py:1243`:

```python
    # combined single-fit invocation BEFORE the adapter provenance read, so the
    # execution manifest (checkpoint + prediction digests) is present in
    # provenance_manifest and binds into effective_model_checksum (spec §2.5/§10)
    combined_pairs = _combined_pair_union(
        inputs.sealed_double_pair_ids, inputs.sealed_single_pair_ids
    )
    adapter_predictions = (
        _predict_combined_adapters(inputs, combined_pairs, adapters) if adapters else None
    )
    # ... then the existing model_artifact_checksums block (phase2a.py:1240-1244):
    #     for name, adapter in sorted(adapters.items()):
    #         model_artifact_checksums[name] = sha256_json(adapter.backend.provenance_manifest)
    #     effective_model_checksum = sha256_json({... "methods": model_artifact_checksums ...})
```

and replace the two `_predict_role` calls (`phase2a.py:1256-1271`) with role splits of the already-computed predictions (no re-invocation):

```python
    double_preds = _predict_role(
        inputs, inputs.sealed_double_pair_ids, fitted, selected_Z, mean_prediction, adapters,
        adapter_predictions=adapter_predictions,
    )
    single_preds = _predict_role(
        inputs, inputs.sealed_single_pair_ids, fitted, selected_Z, mean_prediction, adapters,
        adapter_predictions=adapter_predictions,
    )
```

Verify the reorder does not change behavior for the in-process path: `model_artifact_checksums` for `fitted` models is computed at `phase2a.py:1240-1242` and is independent of `adapter_predictions`; only the adapter entries now reflect a post-predict `provenance_manifest`. If an existing phase2a test pins a literal `effective_model_checksum` for a subprocess adapter, update that expected value (the manifest legitimately now includes the execution digests); a structural assertion needs no change.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/alive/compose/test_phase2a.py -q`
Expected: PASS — the combined-invocation test plus every existing phase2a test (the split still feeds `FrozenPredictionBundle.create` the same per-role structure, now sourced from one combined call).

- [ ] **Step 5: Run the full compose suite + ruff, then commit**

Run: `uv run pytest tests/alive/compose -q && uv run ruff check src/alive/compose tests/alive/compose && uv run ruff format --check src/alive/compose tests/alive/compose`
Expected: all green.

```bash
git add src/alive/compose/phase2a.py tests/alive/compose/test_phase2a.py
git commit -m "feat(compose): subprocess adapters fit once on the combined pair union (A2 task 8)"
```

---

## Self-Review (completed by plan author)

**Spec coverage:** A1 dependency closure → Task 0. §2.1 fit_role block → Task 0 (semantic/lineage guard) + Task 4 (payload validation + v2 emission). §2.2 response_projection → Task 1 (serialize) + Task 4 (shape/digest validation + v2 emission, atomic with the validator flip) + Task 6 (independent equality to `Phase2aInputs.response_space_checksum`). §2.3 operator → Task 2. §2.4 representation → Task 2 (operator branches) + Task 5 (committed per-method lock and bias-report requirement). §2.5 single fit/checkpoint + manifest → Task 5 (controller verification) + Task 7 (write-once checkpoint and pair-associated reference predictions) + **Task 8 (combined single subprocess invocation in `run_phase2a`)**. §5.1 negative leakage includes outside-root, role-token disguise, source-lineage, shape and digest tamper. §6 known-answer → Task 2. §7.2 modified files → Tasks 4/5/6/8 + response.py Task 3 + stub Task 5/7 + config registration Task 5. §8 integration → Task 7. §9 fail-closed → controller and worker guards both reject. §10 completion → Task 4 source binding + Task 6 response-artifact binding + Task 7 checkpoint + Task 8 single invocation + full-suite/ruff gate. **Deferred (NOT A2):** durable final ledger + seed variability (D), real-data driver assembly (C); the A2 interfaces needed by C are nevertheless explicit and fail closed.

**Fixture-code scope:** T6/T7/T8 fixture assembly remains intentionally abbreviated because it reuses existing test factories, but its data, identity, root, representation and pair-alignment requirements are closed by the explicit **Fixture contract**. No production algorithm or trust decision is delegated to the implementer.

**Type consistency:** `read_predictions` returns `tuple[dict, dict]` from Task 5 onward; `predict` unpacks then controller-verifies it. `SubprocessBaselineBackend` requires the trusted root, response checksum and `ExecutionIdentityLock`. `build_response_projection(response_space, *, gene_order, control_mean, raw_data_sha256)` is consistent across Tasks 1/6. `apply_response_projection(block, x, gene_order, *, representation)` is consistent across Tasks 2/7. `build_subprocess_fit_payload` binds `response_artifact_sha256` to `inputs.response_space_checksum`. `_predict_role`'s new `adapter_predictions` kwarg defaults to `None`; `run_phase2a` passes the combined-once result.

**Independent-review remediation (2026-07-04):** (a) added blocking Task 0 for A1 role/lineage bypasses; (b) replaced self-derived artifact roots with an out-of-band trusted root; (c) bound projection SHA to the verified Phase2a response artifact; (d) changed execution manifests from worker self-report to controller-verified evidence, including a real checkpoint sidecar; (e) locked representation per method and required pseudobulk bias evidence; (f) made the reference integration pair-associated rather than returning one shared delta.

**Iteration-1 gate fixes (spec-review loop, iteration 1 → NEEDS_IMPROVEMENT):** (a) `design_sound` NO — Task 7 now migrates/deletes the two additive predict-through-adapter tests broken by the operator stub (Step 4), so every task ends green; (b) §2.5 double-fit — added **Task 8** so subprocess adapters fit once on the combined union (was wrongly deferred by the old decision #3); (c) fixture ambiguity — added the **Fixture contract** and `_subprocess_adapters(…, tmp_path)` threading; (d) readability — replaced the stub's inline `__import__` with a top-level import.

**Iteration-2 gate fix (iteration 2 → PASS, one med advisory resolved post-gate):** the verifier noted the §10 method-lock binding was overstated — `run_phase2a` read `provenance_manifest` at `phase2a.py:1243` *before* any predict, so the execution manifest never reached `effective_model_checksum`. **Task 8 Step 3 now orders the combined predict before that read**, and the Task 5 note is corrected to say `provenance_manifest` only *carries* the digests post-predict while Task 8 realizes the actual binding.

**Iteration-3 gate fixes (iteration 3 → NEEDS_IMPROVEMENT on the owner's hardening pass; `internally_consistent` = no):** the loop caught two task-sequencing breakages of the "each task ends full-suite green" invariant. (1) The `_validate_payload` v2 flip (Task 4) and the `build_subprocess_fit_payload` emitter flip (was Task 6) were in separate tasks, so `_subprocess_adapters` failed `configure_payload` and `test_phase2a` was red at Tasks 4–5 → the emitter migration + `_subprocess_adapters` fixture upgrade + the v2-consistency test are now **atomic in Task 4** (Step 3b), and Task 6 narrows to the independent `response_artifact_sha256`↔`response_space_checksum` binding + its divergence test. (2) Task 5 added three *required* backend fields but updated only the integration test → Task 5 now explicitly updates **every** `SubprocessBaselineBackend(...)` site (`_backend()`, the three `test_is_available_*`, `_subprocess_adapters`) with test-appropriate values; `test_payload_with_sealed_token_is_refused` still passes because the sealed-token scan runs before the response-artifact check.

**Iteration-4 gate fixes (iteration 4 → NEEDS_IMPROVEMENT · MAX_ITER · human checkpoint):** the loop caught a residual instance of the same construction-site failure mode plus a hard bug. (a) A **sixth** `SubprocessBaselineBackend(...)` site — `tests/alive/compose/test_baseline_failclosed.py:31` — was not enumerated; Task 5's list is now grep-derived (six sites across three files) and Step 4 runs the **whole compose dir** (not one file) so a missed cross-file site can't hide. (b) **Dataclass ordering:** the three new required fields placed after the defaulted `seed: int = 11` would raise `non-default argument follows default argument` at class-definition time; Task 5 now marks them keyword-only via `dataclasses.KW_ONLY`. The spec-review profile's `max_iterations=3` tripped (MAX_ITER + NO_PROGRESS on `internally_consistent`) — the loop's signal to stop auto-iterating and hand to a human review; these fixes were applied post-gate and are pending the owner's final review (no further auto-gate).

**Post-implementation (not a code task):** run the **science-dev loop gate** (LOCAL harness) on the A2 increment — expected anchors `seal_access_zero`, `no_outcome_selected_test_set`, `fit_on_training_roles_only`, `protocol_versioned`/`baseline_registered` → yes/n-a (spec §10.2) — then `finishing-a-development-branch`.

## Execution Handoff

Two execution options:
1. **Subagent-Driven (recommended)** — fresh subagent per task, spec+quality review between tasks, broad final review.
2. **Inline Execution** — batch execution with checkpoints.
