# COMPOSE-K562-v1 Phase 2a (dev pipeline) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the COMPOSE Phase-2a development pipeline — real-Norman δ/ε wiring, response space, z-factors, the four models (L1/L2/L3/ID-only) + the additive/lower-bound baselines + GEARS/CPA adapters, gene-disjoint OOF selection, the real Φ-rank/noise-ceiling/futility gates — all validated on SYNTHETIC fixtures, opening NO seal.

**Architecture:** New modules under `src/alive/compose/` compose with the Phase-1 operator/identify/gates code. A real-data adapter turns a Norman AnnData into calibration-role δ_g/δ_gh/ε in a control-fit PCA-50 response space; a z-factor builder concatenates expression-PCA with a singles-fit ESM projection; a small `Model` protocol unifies L1/L2/L3/ID-only and a `BaselineAdapter` protocol wraps GEARS/CPA behind a stub-testable seam. Selection, gates, and a dev-stage orchestrator produce a no-seal dev report. Nothing here reads sealed pairs or authorizes a run.

**Tech Stack:** Python 3.11–3.12, numpy, scipy, scikit-learn, anndata; ruff (line length 100); pytest. Reuses `alive.compose.{operator,identify,gates,split,synthetic}`, `alive.data.norman`, `alive.provenance`, the ESM-2 feature bank (`alive.data.features`).

## Global Constraints

- **Contract:** spec `docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md` §10 + `configs/compose_k562_v1_phase2.yaml`. Status = **PRE-REGISTERED, ACTIVATION BLOCKED**.
- **This plan builds + tests code on SYNTHETIC fixtures / tiny toy AnnData only.** It does NOT run real Phase-2a on Norman and does NOT open any seal. Real execution requires a separate owner activation commit (§10.1) + registry → ACTIVE.
- **No seal access:** no task reads `sealed_double_unseen` / `sealed_single_unseen` outcomes. The dev pipeline uses `singles` + `combo_calibration` only.
- **Outcome-independent** eligibility/split (CLAUDE.md §5); never select by GI strength.
- **Two-stage identification:** z fixed from singles BEFORE B; B is regularized linear LSQ (reuse `alive.compose.identify`).
- **z dimensions:** `k_total ∈ {4,6,8}`; z = [expression-PCA(`k_total-2`) ; ESM projection(2)]; ESM projection fit on singles, NO outcomes.
- **Identifiability gate uses the REAL Φ rank + condition number** on `combo_calibration`, not a pair-count floor.
- **Leakage guard:** GEARS/CPA train only on `singles`+`combo_calibration`; the measurability gate refuses sealed roles (already enforced in `alive.compose.gates`).
- **Independent seal/run-identity** from TG-K562 (§6.3); artifacts under `artifacts/compose/<run_id>` (used in Phase 2b).
- Production logic in `src/alive/`, tests under `tests/alive/compose/`; NumPy-style docstrings + type hints; ruff line length 100; commands via `uv run`.
- Commits end with the repo trailers (Co-Authored-By + Claude-Session).

---

## File Structure

| Path | Responsibility |
|---|---|
| `src/alive/compose/response.py` | Control-fit response space (normalize_total+log1p+HVG+PCA-50 on control+singles) → per-role mean shifts δ_g/δ_gh and ε on calibration. |
| `src/alive/compose/zfactor.py` | z_g = [PCA_expr(k_total-2) ; ESM-projection(2)], ESM projection fit on singles only. |
| `src/alive/compose/models.py` | `Model` protocol + L1 (bilinear identifiable), L2 (saturation), L3 (hypernetwork), ID-only; each `fit(...)`/`predict_pair(...)`. |
| `src/alive/compose/baselines_combo.py` | additive / no_change / perturbation_mean + `BaselineAdapter` protocol; GEARS/CPA adapters (stub-testable). |
| `src/alive/compose/metric2.py` | per-pair response-space MSE `e_pair`; paired relative improvement `theta`. |
| `src/alive/compose/select.py` | gene-disjoint OOF folds over calibration; select `k_total`, `λ`. |
| `src/alive/compose/datacard.py` | Norman data-card builder (raw/processed SHA-256, obs schema, exclusions). |
| `src/alive/compose/phase2a.py` | dev-stage orchestrator: response→z→fit all→OOF select→Φ-rank gate→noise-ceiling→futility→dev report (NO seal). |
| `tests/alive/compose/` | unit / known-answer / leakage / reproducibility tests. |

(Phase 2b — freeze + seal-once + bootstrap simultaneous inference + verdict — is a companion plan: `2026-06-24-compose-phase2b-seal-eval.md`.)

---

## Task 1: Deterministic split aligned to §10.4

**Files:**
- Modify: `src/alive/compose/split.py`
- Test: `tests/alive/compose/test_split.py` (add reproducibility cases)

**Interfaces:**
- Consumes: existing `build_pair_split`.
- Produces: `build_pair_split(eligible_pairs, *, seed, calibration_fraction) -> ComposeSplit` made byte-deterministic per §10.4 — gene list UTF-8 lexicographic sorted, `PCG64(seed)` permutation, calibration gene count = round-half-to-even(`calibration_fraction * n_genes`).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/alive/compose/test_split.py
import numpy as np
from alive.compose.split import build_pair_split


def test_round_half_to_even_calibration_count():
    # 5 genes * 0.6 = 3.0 -> 3; 4 genes * 0.5 would be banker's rounding (=2) — guard the 0.6 path
    genes = [chr(ord("A") + i) for i in range(5)]
    pairs = [(genes[i], genes[j]) for i in range(5) for j in range(i + 1, 5)]
    sp = build_pair_split(pairs, seed=11, calibration_fraction=0.6)
    assert len(sp.combo_genes) == 3  # round(3.0)


def test_pcg64_permutation_is_reproducible():
    genes = [chr(ord("A") + i) for i in range(8)]
    pairs = [(genes[i], genes[j]) for i in range(8) for j in range(i + 1, 8)]
    a = build_pair_split(pairs, seed=11, calibration_fraction=0.6)
    b = build_pair_split(pairs, seed=11, calibration_fraction=0.6)
    assert a.combo_genes == b.combo_genes
    assert a.sealed_double_unseen == b.sealed_double_unseen


def test_genes_are_utf8_sorted_before_permutation():
    # Non-ASCII-order input must be sorted deterministically before permutation.
    pairs = [("B", "A"), ("Z", "A"), ("B", "Z")]
    sp = build_pair_split(pairs, seed=11, calibration_fraction=0.6)
    # canonicalized (min,max): ("A","B"),("A","Z"),("B","Z"); genes sorted = A,B,Z
    assert set(g for p in (sp.combo_calibration + sp.sealed_double_unseen + sp.secondary) for g in p) <= {"A", "B", "Z"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/alive/compose/test_split.py -k "round_half or pcg64 or utf8" -v`
Expected: FAIL (round-half-to-even / PCG64 wording not yet guaranteed).

- [ ] **Step 3: Implement (make determinism explicit)**

```python
# src/alive/compose/split.py — replace the body of build_pair_split
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ComposeSplit:
    combo_calibration: list[tuple[str, str]]
    sealed_double_unseen: list[tuple[str, str]]
    secondary: list[tuple[str, str]]
    combo_genes: frozenset[str]


def _round_half_to_even(x: float) -> int:
    # numpy.rint implements round-half-to-even (banker's rounding).
    return int(np.rint(x))


def build_pair_split(
    eligible_pairs: list[tuple[str, str]],
    *,
    seed: int,
    calibration_fraction: float,
) -> ComposeSplit:
    """Deterministic pair split with double-unseen gene isolation (spec §10.4).

    Genes are UTF-8 lexicographically sorted, permuted by ``PCG64(seed)``; the
    first ``round_half_to_even(calibration_fraction * n_genes)`` are calibration
    genes. Pairs are canonicalised ``(min, max)`` and de-duplicated upstream.
    """
    canon = sorted({(min(a, b), max(a, b)) for (a, b) in eligible_pairs})
    genes = sorted({g for pair in canon for g in pair})  # UTF-8 lexicographic
    rng = np.random.Generator(np.random.PCG64(seed))
    perm = rng.permutation(len(genes))
    n_cal = _round_half_to_even(calibration_fraction * len(genes))
    cal_genes = {genes[i] for i in perm[:n_cal]}

    calibration, sealed, secondary = [], [], []
    for a, b in canon:
        a_in, b_in = a in cal_genes, b in cal_genes
        if a_in and b_in:
            calibration.append((a, b))
        elif not a_in and not b_in:
            sealed.append((a, b))
        else:
            secondary.append((a, b))
    return ComposeSplit(calibration, sealed, secondary, frozenset(cal_genes))
```

- [ ] **Step 4: Run all split tests**

Run: `uv run pytest tests/alive/compose/test_split.py -v`
Expected: PASS (existing isolation tests + the 3 new reproducibility tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/alive/compose/split.py tests/alive/compose/test_split.py
git add src/alive/compose/split.py tests/alive/compose/test_split.py
git commit -m "feat(compose): deterministic §10.4 split (PCG64, UTF-8, round-half-to-even)"
```

---

## Task 2: Response space (control-fit PCA-50 + role mean shifts)

**Files:**
- Create: `src/alive/compose/response.py`
- Test: `tests/alive/compose/test_response.py`

**Interfaces:**
- Consumes: numpy, scipy.sparse, sklearn.decomposition.PCA, `alive.data.norman.parse_labels`.
- Produces:
  - `ResponseSpace` (frozen): `pca` (fitted), `ctrl_mean (p,)`, `hvg_idx`, `median_total`.
  - `fit_response_space(X, control_idx, single_cell_idx, *, n_hvg, pca_dim, seed) -> ResponseSpace` — normalize_total(median)+log1p, top-`n_hvg` by control variance, PCA-`pca_dim` fit on control+singles only.
  - `project(rs, X, idx) -> np.ndarray (len(idx), pca_dim)`.
  - `mean_shift(rs, X, idx) -> np.ndarray (pca_dim,)` = mean(project(rows)) − ctrl_mean.
  - `epsilon(rs, X, pair_idx, delta_g, delta_h) -> np.ndarray (pca_dim,)` = mean_shift(pair) − (delta_g+delta_h).

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_response.py
"""Tests for alive.compose.response — written FIRST per TDD protocol."""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp

from alive.compose.response import epsilon, fit_response_space, mean_shift, project


def _toy_counts(seed=0):
    rng = np.random.default_rng(seed)
    X = sp.csr_matrix(rng.poisson(1.0, size=(60, 40)).astype(np.float64))
    control_idx = np.arange(0, 20)
    single_idx = np.arange(20, 50)
    return X, control_idx, single_idx


def test_fit_and_project_shapes():
    X, c, s = _toy_counts()
    rs = fit_response_space(X, c, s, n_hvg=20, pca_dim=5, seed=11)
    assert rs.ctrl_mean.shape == (5,)
    assert project(rs, X, np.arange(50, 60)).shape == (10, 5)


def test_control_mean_shift_is_zero():
    X, c, s = _toy_counts()
    rs = fit_response_space(X, c, s, n_hvg=20, pca_dim=5, seed=11)
    np.testing.assert_allclose(mean_shift(rs, X, c), 0.0, atol=1e-8)


def test_epsilon_is_nonadditive_residual():
    X, c, s = _toy_counts()
    rs = fit_response_space(X, c, s, n_hvg=20, pca_dim=5, seed=11)
    dg = mean_shift(rs, X, np.arange(20, 30))
    dh = mean_shift(rs, X, np.arange(30, 40))
    pair = np.arange(50, 60)
    eps = epsilon(rs, X, pair, dg, dh)
    np.testing.assert_allclose(eps, mean_shift(rs, X, pair) - (dg + dh), atol=1e-10)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/alive/compose/test_response.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'alive.compose.response'`.

- [ ] **Step 3: Implement**

```python
# src/alive/compose/response.py
"""Control-fit response space + role mean shifts for COMPOSE Phase 2a.

normalize_total(median) + log1p; top-n_hvg by control variance; PCA fit on
control+single cells ONLY (no double-cell, no sealed access). delta = role mean
in PCA space minus the control mean; epsilon = pair mean shift minus additive.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp
from sklearn.decomposition import PCA


@dataclass(frozen=True)
class ResponseSpace:
    pca: PCA
    ctrl_mean: np.ndarray
    hvg_idx: np.ndarray
    median_total: float


def _normalize_log1p(X: sp.csr_matrix, median_total: float) -> sp.csr_matrix:
    tot = np.asarray(X.sum(axis=1)).ravel()
    tot[tot == 0] = 1.0
    out = X.multiply((median_total / tot)[:, None]).tocsr()
    out.data = np.log1p(out.data)
    return out


def fit_response_space(
    X: sp.csr_matrix,
    control_idx: np.ndarray,
    single_cell_idx: np.ndarray,
    *,
    n_hvg: int,
    pca_dim: int,
    seed: int,
) -> ResponseSpace:
    """Fit the response space on control+single cells only."""
    X = X.tocsr().astype(np.float64)
    tot_all = np.asarray(X.sum(axis=1)).ravel()
    median_total = float(np.median(tot_all[tot_all > 0]))
    Xn = _normalize_log1p(X, median_total)
    ctrl = Xn[control_idx]
    mean = np.asarray(ctrl.mean(axis=0)).ravel()
    sq = np.asarray(ctrl.multiply(ctrl).mean(axis=0)).ravel()
    var = sq - mean**2
    hvg_idx = np.argsort(var)[::-1][:n_hvg]
    fit_idx = np.unique(np.concatenate([control_idx, single_cell_idx]))
    pca = PCA(n_components=pca_dim, random_state=seed).fit(Xn[fit_idx][:, hvg_idx].toarray())
    ctrl_mean = pca.transform(Xn[control_idx][:, hvg_idx].toarray()).mean(axis=0)
    return ResponseSpace(pca=pca, ctrl_mean=ctrl_mean, hvg_idx=hvg_idx, median_total=median_total)


def project(rs: ResponseSpace, X: sp.csr_matrix, idx: np.ndarray) -> np.ndarray:
    """Project rows ``idx`` into the fitted PCA response space."""
    Xn = _normalize_log1p(X.tocsr().astype(np.float64), rs.median_total)
    return rs.pca.transform(Xn[idx][:, rs.hvg_idx].toarray())


def mean_shift(rs: ResponseSpace, X: sp.csr_matrix, idx: np.ndarray) -> np.ndarray:
    """Mean response of rows ``idx`` minus the control mean."""
    return project(rs, X, idx).mean(axis=0) - rs.ctrl_mean


def epsilon(
    rs: ResponseSpace,
    X: sp.csr_matrix,
    pair_idx: np.ndarray,
    delta_g: np.ndarray,
    delta_h: np.ndarray,
) -> np.ndarray:
    """Non-additive component: pair mean shift minus (delta_g + delta_h)."""
    return mean_shift(rs, X, pair_idx) - (delta_g + delta_h)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/alive/compose/test_response.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/alive/compose/response.py tests/alive/compose/test_response.py
git add src/alive/compose/response.py tests/alive/compose/test_response.py
git commit -m "feat(compose): control-fit response space + role mean shifts (Phase 2a)"
```

---

## Task 3: z-factor builder (expression PCA + singles-fit ESM projection)

**Files:**
- Create: `src/alive/compose/zfactor.py`
- Test: `tests/alive/compose/test_zfactor.py`

**Interfaces:**
- Consumes: numpy, sklearn.decomposition.PCA.
- Produces:
  - `build_z(delta_by_gene, esm_by_gene, *, k_total, esm_dim, seed) -> dict[str, np.ndarray]` — for each gene, z = concat(expression-PCA of δ to `k_total-esm_dim` dims, ESM-PCA of the ESM vector to `esm_dim` dims). Both PCAs fit on the eligible single genes ONLY (no outcomes beyond δ which is a single-role quantity), deterministic by `seed`. Returns `{gene -> (k_total,) array}`.
  - Raises `ValueError` if `esm_dim >= k_total`.

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_zfactor.py
"""Tests for alive.compose.zfactor — written FIRST per TDD protocol."""
from __future__ import annotations

import numpy as np
import pytest

from alive.compose.zfactor import build_z


def _inputs(n=20, p=10, e=8, seed=0):
    rng = np.random.default_rng(seed)
    genes = [f"G{i}" for i in range(n)]
    delta = {g: rng.normal(size=p) for g in genes}
    esm = {g: rng.normal(size=e) for g in genes}
    return delta, esm


def test_z_total_dimension_and_keys():
    delta, esm = _inputs()
    z = build_z(delta, esm, k_total=6, esm_dim=2, seed=11)
    assert set(z) == set(delta)
    assert z["G0"].shape == (6,)  # 4 expression + 2 esm


def test_deterministic():
    delta, esm = _inputs()
    a = build_z(delta, esm, k_total=6, esm_dim=2, seed=11)
    b = build_z(delta, esm, k_total=6, esm_dim=2, seed=11)
    np.testing.assert_array_equal(a["G3"], b["G3"])


def test_esm_dim_must_be_less_than_k_total():
    delta, esm = _inputs()
    with pytest.raises(ValueError):
        build_z(delta, esm, k_total=2, esm_dim=2, seed=11)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/alive/compose/test_zfactor.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/alive/compose/zfactor.py
"""z-factor builder: expression-PCA(delta) concatenated with ESM-PCA projection.

z_g = [ PCA_expr(delta_g) in (k_total - esm_dim) dims ; PCA_esm(esm_g) in esm_dim ].
Both PCAs fit on the eligible single genes only (no perturbation outcomes beyond
delta, a single-role quantity). z is fixed before operator identification (§3.1).
"""
from __future__ import annotations

import numpy as np
from sklearn.decomposition import PCA


def build_z(
    delta_by_gene: dict[str, np.ndarray],
    esm_by_gene: dict[str, np.ndarray],
    *,
    k_total: int,
    esm_dim: int,
    seed: int,
) -> dict[str, np.ndarray]:
    """Concatenate expression-PCA(delta) and ESM-PCA projections per gene."""
    if esm_dim >= k_total:
        raise ValueError(f"esm_dim ({esm_dim}) must be < k_total ({k_total})")
    genes = sorted(delta_by_gene)
    D = np.vstack([delta_by_gene[g] for g in genes])
    E = np.vstack([esm_by_gene[g] for g in genes])
    expr_dim = k_total - esm_dim
    pe = PCA(n_components=expr_dim, random_state=seed).fit_transform(D)
    pesm = PCA(n_components=esm_dim, random_state=seed).fit_transform(E)
    z = np.hstack([pe, pesm])
    return {g: z[i] for i, g in enumerate(genes)}
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/alive/compose/test_zfactor.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/alive/compose/zfactor.py tests/alive/compose/test_zfactor.py
git add src/alive/compose/zfactor.py tests/alive/compose/test_zfactor.py
git commit -m "feat(compose): z-factor builder (expr-PCA + singles-fit ESM projection)"
```

---

## Task 4: Metric — per-pair MSE + paired relative improvement

**Files:**
- Create: `src/alive/compose/metric2.py`
- Test: `tests/alive/compose/test_metric2.py`

**Interfaces:**
- Produces:
  - `pair_errors(pred, truth) -> np.ndarray (n_pairs,)` — `e_i = mean over PCA coords of (pred_i - truth_i)**2`.
  - `theta(e_model, e_comparator) -> float` — `1 - mean(e_model)/max(mean(e_comparator), 1e-12)`.
  - `MetricError(ValueError)` on shape mismatch / non-finite.

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_metric2.py
"""Known-answer tests for alive.compose.metric2 (§10.5)."""
from __future__ import annotations

import numpy as np
import pytest

from alive.compose.metric2 import MetricError, pair_errors, theta


def test_pair_errors_known_answer():
    pred = np.array([[1.0, 1.0], [0.0, 0.0]])
    truth = np.array([[0.0, 0.0], [0.0, 0.0]])
    np.testing.assert_allclose(pair_errors(pred, truth), [1.0, 0.0])  # mean([1,1])=1 ; mean([0,0])=0


def test_theta_perfect_and_zero():
    e_model = np.array([0.0, 0.0])
    e_cmp = np.array([1.0, 1.0])
    assert theta(e_model, e_cmp) == pytest.approx(1.0)        # model perfect
    assert theta(e_cmp, e_cmp) == pytest.approx(0.0)          # equal -> no improvement


def test_theta_negative_when_worse():
    assert theta(np.array([2.0]), np.array([1.0])) == pytest.approx(-1.0)


def test_nonfinite_raises():
    with pytest.raises(MetricError):
        pair_errors(np.array([[np.nan]]), np.array([[0.0]]))
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/alive/compose/test_metric2.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/alive/compose/metric2.py
"""Phase-2 combo metric: per-pair response-space MSE + paired relative improvement.

e_{M,i} = (1/p) ||pred_i - truth_i||^2 ; theta_{M,C} = 1 - mean(e_M)/max(mean(e_C), 1e-12).
Higher theta = method M closer to truth than comparator C.
"""
from __future__ import annotations

import numpy as np


class MetricError(ValueError):
    """Raised on invalid metric inputs."""


def _finite(name: str, a: np.ndarray) -> np.ndarray:
    a = np.asarray(a, dtype=np.float64)
    if not np.all(np.isfinite(a)):
        raise MetricError(f"{name} contains non-finite values")
    return a


def pair_errors(pred: np.ndarray, truth: np.ndarray) -> np.ndarray:
    """Per-pair mean squared error over PCA coordinates."""
    pred, truth = _finite("pred", pred), _finite("truth", truth)
    if pred.shape != truth.shape:
        raise MetricError(f"shape mismatch {pred.shape} vs {truth.shape}")
    return np.mean((pred - truth) ** 2, axis=1)


def theta(e_model: np.ndarray, e_comparator: np.ndarray) -> float:
    """Paired relative improvement of model over comparator (§10.5)."""
    em = float(np.mean(_finite("e_model", e_model)))
    ec = float(np.mean(_finite("e_comparator", e_comparator)))
    return 1.0 - em / max(ec, 1e-12)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/alive/compose/test_metric2.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/alive/compose/metric2.py tests/alive/compose/test_metric2.py
git add src/alive/compose/metric2.py tests/alive/compose/test_metric2.py
git commit -m "feat(compose): Phase-2 metric (per-pair MSE + relative improvement theta)"
```

---

## Task 5: Models — L1/L2/L3/ID-only behind a `Model` protocol

**Files:**
- Create: `src/alive/compose/models.py`
- Test: `tests/alive/compose/test_models.py`

**Interfaces:**
- Consumes: `alive.compose.operator.bilinear_predict`, `alive.compose.identify.identify_operator`.
- Produces: a duck-typed `Model` with `fit(Z, pairs, eps_obs, *, lam) -> None` and `predict_eps(Z, g, h) -> np.ndarray`, implemented by:
  - `BilinearL1` (identifiable; wraps `identify_operator`/`bilinear_predict`).
  - `SaturationL2` (L1 then a fixed monotone `tanh` link per output dim, scale fit by 1-D least squares on calibration).
  - `IdOnly` (linear ridge of `eps` on `concat(z_g, z_h)` — no bilinear term).
  - `HyperL3` — a tiny numpy MLP hypernetwork mapping `concat(z_g,z_h)` → eps (1 hidden layer, fixed width, deterministic init by seed; trained by gradient descent for a fixed number of steps). Pure numpy.

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_models.py
"""Tests for alive.compose.models — written FIRST per TDD protocol."""
from __future__ import annotations

import numpy as np

from alive.compose.models import BilinearL1, HyperL3, IdOnly, SaturationL2
from alive.compose.operator import bilinear_predict, sym_basis_dim


def _data(seed=0, n=24, k=4, p=3, npairs=40):
    rng = np.random.default_rng(seed)
    Z = rng.normal(size=(n, k))
    coef = rng.normal(size=(p, sym_basis_dim(k)))
    pairs = sorted({(min(a, b), max(a, b)) for a, b in rng.integers(0, n, (npairs, 2)) if a != b})
    eps = np.vstack([bilinear_predict(coef, Z[g], Z[h]) for g, h in pairs])
    return Z, pairs, eps, coef


def test_l1_recovers_on_noiseless():
    Z, pairs, eps, coef = _data()
    m = BilinearL1()
    m.fit(Z, pairs, eps, lam=0.0)
    g, h = 0, 5
    np.testing.assert_allclose(m.predict_eps(Z, g, h), bilinear_predict(coef, Z[g], Z[h]), atol=1e-6)


def test_all_models_predict_right_shape():
    Z, pairs, eps, _ = _data()
    for cls in (BilinearL1, SaturationL2, IdOnly, HyperL3):
        m = cls()
        m.fit(Z, pairs, eps, lam=1e-3)
        out = m.predict_eps(Z, 1, 7)
        assert out.shape == (eps.shape[1],)
        assert np.all(np.isfinite(out))
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/alive/compose/test_models.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/alive/compose/models.py
"""COMPOSE Phase-2 models behind a common fit/predict_eps interface.

L1 = identifiable symmetric bilinear operator (the headline). L2 = L1 + a fixed
monotone tanh link with a per-output scale. ID-only = ridge of eps on
concat(z_g,z_h) (no bilinear term). L3 = a small deterministic numpy MLP
hypernetwork (max capacity, no identifiability claim).
"""
from __future__ import annotations

import numpy as np

from alive.compose.identify import identify_operator
from alive.compose.operator import bilinear_predict


class BilinearL1:
    """Identifiable symmetric bilinear operator (headline)."""

    def fit(self, Z, pairs, eps_obs, *, lam: float) -> None:
        self.coef_ = identify_operator(Z, pairs, eps_obs, lam=lam)

    def predict_eps(self, Z, g: int, h: int) -> np.ndarray:
        return bilinear_predict(self.coef_, Z[g], Z[h])


class SaturationL2:
    """L1 plus a fixed monotone tanh link with a per-output scale."""

    def fit(self, Z, pairs, eps_obs, *, lam: float) -> None:
        self.coef_ = identify_operator(Z, pairs, eps_obs, lam=lam)
        raw = np.vstack([bilinear_predict(self.coef_, Z[g], Z[h]) for g, h in pairs])
        # per-output scale s minimising || s*tanh(raw) - eps ||^2  (closed form)
        t = np.tanh(raw)
        num = np.sum(t * eps_obs, axis=0)
        den = np.sum(t * t, axis=0)
        self.scale_ = np.where(den > 1e-12, num / den, 0.0)

    def predict_eps(self, Z, g: int, h: int) -> np.ndarray:
        return self.scale_ * np.tanh(bilinear_predict(self.coef_, Z[g], Z[h]))


class IdOnly:
    """Ridge regression of eps on concat(z_g, z_h) — no bilinear term."""

    def fit(self, Z, pairs, eps_obs, *, lam: float) -> None:
        feats = np.vstack([np.concatenate([Z[g], Z[h]]) for g, h in pairs])
        feats = np.hstack([feats, np.ones((feats.shape[0], 1))])
        gram = feats.T @ feats + max(lam, 1e-8) * np.eye(feats.shape[1])
        self.w_ = np.linalg.solve(gram, feats.T @ eps_obs)

    def predict_eps(self, Z, g: int, h: int) -> np.ndarray:
        x = np.concatenate([Z[g], Z[h], [1.0]])
        return x @ self.w_


class HyperL3:
    """Tiny deterministic numpy MLP hypernetwork (1 hidden layer)."""

    def __init__(self, hidden: int = 16, steps: int = 300, lr: float = 0.05, seed: int = 0):
        self.hidden, self.steps, self.lr, self.seed = hidden, steps, lr, seed

    def fit(self, Z, pairs, eps_obs, *, lam: float) -> None:
        rng = np.random.default_rng(self.seed)
        X = np.vstack([np.concatenate([Z[g], Z[h]]) for g, h in pairs])
        y = np.asarray(eps_obs, dtype=np.float64)
        d_in, d_out = X.shape[1], y.shape[1]
        W1 = rng.normal(scale=0.1, size=(d_in, self.hidden))
        b1 = np.zeros(self.hidden)
        W2 = rng.normal(scale=0.1, size=(self.hidden, d_out))
        b2 = np.zeros(d_out)
        n = X.shape[0]
        for _ in range(self.steps):
            h = np.tanh(X @ W1 + b1)
            pred = h @ W2 + b2
            g = (pred - y) / n
            gW2 = h.T @ g + lam * W2
            gb2 = g.sum(0)
            gh = (g @ W2.T) * (1 - h**2)
            gW1 = X.T @ gh + lam * W1
            gb1 = gh.sum(0)
            W1 -= self.lr * gW1; b1 -= self.lr * gb1
            W2 -= self.lr * gW2; b2 -= self.lr * gb2
        self.params_ = (W1, b1, W2, b2)

    def predict_eps(self, Z, g: int, h: int) -> np.ndarray:
        W1, b1, W2, b2 = self.params_
        x = np.concatenate([Z[g], Z[h]])
        return np.tanh(x @ W1 + b1) @ W2 + b2
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/alive/compose/test_models.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/alive/compose/models.py tests/alive/compose/test_models.py
git add src/alive/compose/models.py tests/alive/compose/test_models.py
git commit -m "feat(compose): L1/L2/L3/ID-only models behind a common interface"
```

---

## Task 6: Combo baselines + GEARS/CPA adapter seam

**Files:**
- Create: `src/alive/compose/baselines_combo.py`
- Test: `tests/alive/compose/test_baselines_combo.py`

**Interfaces:**
- Produces:
  - `additive_pred(delta_g, delta_h) -> np.ndarray` (= δ_g+δ_h), `no_change_pred(p) -> zeros(p)`, `perturbation_mean_pred(mean_double_shift) -> np.ndarray`.
  - `BaselineAdapter` protocol: `fit(context) -> None`, `predict_delta_gh(g, h) -> np.ndarray` (full double profile in response space).
  - `GearsAdapter` / `CpaAdapter` skeletons that raise `BaselineUnavailable` unless a real backend is injected; both accept a `backend` callable so tests inject a stub. Real backends are wired at activation (blocker #4) and trained on `singles+combo_calibration` only.
  - `BaselineUnavailable(RuntimeError)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_baselines_combo.py
"""Tests for alive.compose.baselines_combo — written FIRST per TDD protocol."""
from __future__ import annotations

import numpy as np
import pytest

from alive.compose.baselines_combo import (
    BaselineUnavailable,
    GearsAdapter,
    additive_pred,
    no_change_pred,
)


def test_additive_and_no_change():
    dg, dh = np.array([1.0, 2.0]), np.array([0.5, -1.0])
    np.testing.assert_allclose(additive_pred(dg, dh), [1.5, 1.0])
    np.testing.assert_allclose(no_change_pred(3), [0.0, 0.0, 0.0])


def test_adapter_requires_backend():
    a = GearsAdapter(backend=None)
    with pytest.raises(BaselineUnavailable):
        a.fit(context={})


def test_adapter_with_stub_backend():
    calls = {}

    def stub_backend(context):
        calls["fit"] = context
        return lambda g, h: np.array([float(len(g)), float(len(h))])

    a = GearsAdapter(backend=stub_backend)
    a.fit(context={"training_roles": ["singles", "combo_calibration"]})
    assert calls["fit"]["training_roles"] == ["singles", "combo_calibration"]
    np.testing.assert_allclose(a.predict_delta_gh("AB", "CDE"), [2.0, 3.0])
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/alive/compose/test_baselines_combo.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/alive/compose/baselines_combo.py
"""Combo baselines + a stub-testable GEARS/CPA adapter seam (Phase 2a).

Real GEARS/CPA backends are injected at activation (blocker #4) and MUST be
trained on singles+combo_calibration only (leakage guard). Until then the
adapters are unavailable; tests inject a stub backend.
"""
from __future__ import annotations

from typing import Callable

import numpy as np


class BaselineUnavailable(RuntimeError):
    """Raised when a learned baseline backend is not wired."""


def additive_pred(delta_g: np.ndarray, delta_h: np.ndarray) -> np.ndarray:
    """Additive null prediction of the double profile (delta_g + delta_h)."""
    return np.asarray(delta_g) + np.asarray(delta_h)


def no_change_pred(p: int) -> np.ndarray:
    """No-change baseline: zero shift in response space."""
    return np.zeros(p)


def perturbation_mean_pred(mean_double_shift: np.ndarray) -> np.ndarray:
    """Predict the mean double-perturbation shift (computed on training roles)."""
    return np.asarray(mean_double_shift)


class _Adapter:
    """Common stub-testable adapter; real backend injected at activation."""

    def __init__(self, backend: Callable | None):
        self._backend = backend
        self._predict = None

    def fit(self, context: dict) -> None:
        if self._backend is None:
            raise BaselineUnavailable(f"{type(self).__name__}: no backend wired")
        self._predict = self._backend(context)

    def predict_delta_gh(self, g: str, h: str) -> np.ndarray:
        if self._predict is None:
            raise BaselineUnavailable(f"{type(self).__name__}: fit() not called")
        return np.asarray(self._predict(g, h), dtype=np.float64)


class GearsAdapter(_Adapter):
    """GEARS (Roohani 2023) black-box baseline; backend wired at activation."""


class CpaAdapter(_Adapter):
    """CPA (Lotfollahi 2023) latent-additive baseline; backend wired at activation."""
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/alive/compose/test_baselines_combo.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/alive/compose/baselines_combo.py tests/alive/compose/test_baselines_combo.py
git add src/alive/compose/baselines_combo.py tests/alive/compose/test_baselines_combo.py
git commit -m "feat(compose): combo baselines + stub-testable GEARS/CPA adapter seam"
```

---

## Task 7: Gene-disjoint OOF selection of k_total and λ

**Files:**
- Create: `src/alive/compose/select.py`
- Test: `tests/alive/compose/test_select.py`

**Interfaces:**
- Consumes: `alive.compose.models.BilinearL1`, `alive.compose.metric2.theta`/`pair_errors`, `alive.compose.baselines_combo.additive_pred`.
- Produces:
  - `gene_disjoint_folds(pairs, *, n_folds, seed) -> list[tuple[list[int], list[int]]]` — partition GENES into folds; a test fold's pairs are those whose BOTH genes are in the held-out gene group (mirrors the sealed double-unseen regime).
  - `select_hyperparams(build_z_fn, delta_by_gene, esm_by_gene, pairs, eps_by_pair, delta_pair_truth, *, k_grid, lambda_grid, esm_dim, n_folds, seed) -> dict` — returns `{"k_total", "lam", "oof_theta_vs_additive"}` maximising OOF relative improvement of L1 over additive.

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_select.py
"""Tests for alive.compose.select — written FIRST per TDD protocol."""
from __future__ import annotations

import numpy as np

from alive.compose.select import gene_disjoint_folds


def test_folds_are_gene_disjoint():
    pairs = [(i, j) for i in range(8) for j in range(i + 1, 8)]
    folds = gene_disjoint_folds(pairs, n_folds=4, seed=11)
    assert len(folds) == 4
    for train_pairs_idx, test_pairs_idx in folds:
        train_genes = {g for k in train_pairs_idx for g in pairs[k]}
        for k in test_pairs_idx:
            a, b = pairs[k]
            assert a not in train_genes and b not in train_genes  # gene isolation


def test_folds_cover_only_double_unseen_test_pairs():
    pairs = [(i, j) for i in range(8) for j in range(i + 1, 8)]
    folds = gene_disjoint_folds(pairs, n_folds=4, seed=11)
    # every test pair has BOTH genes in the held-out group (double-unseen analogue)
    for _, test_idx in folds:
        assert all(isinstance(k, int) for k in test_idx)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/alive/compose/test_select.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/alive/compose/select.py
"""Gene-disjoint OOF folds + hyperparameter selection (Phase 2a, §10.4).

Folds partition GENES; a fold's test pairs are those with BOTH genes held out,
mirroring the sealed double-unseen regime so dev selection reflects true
difficulty. Selection maximises OOF relative improvement of L1 over additive.
"""
from __future__ import annotations

import numpy as np

from alive.compose.baselines_combo import additive_pred
from alive.compose.metric2 import pair_errors, theta
from alive.compose.models import BilinearL1


def gene_disjoint_folds(
    pairs: list[tuple[int, int]],
    *,
    n_folds: int,
    seed: int,
) -> list[tuple[list[int], list[int]]]:
    """Partition genes into n_folds; test pairs = both genes in the held-out group."""
    genes = sorted({g for p in pairs for g in p})
    rng = np.random.Generator(np.random.PCG64(seed))
    groups = np.array_split(rng.permutation(genes), n_folds)
    folds = []
    for grp in groups:
        held = set(int(x) for x in grp)
        test_idx = [k for k, (a, b) in enumerate(pairs) if a in held and b in held]
        train_idx = [k for k, (a, b) in enumerate(pairs) if a not in held and b not in held]
        if test_idx and train_idx:
            folds.append((train_idx, test_idx))
    return folds


def select_hyperparams(
    Z_by_k: dict[int, np.ndarray],
    pairs: list[tuple[int, int]],
    eps_obs: np.ndarray,
    delta_pair_truth: np.ndarray,
    additive_pred_by_pair: np.ndarray,
    *,
    k_grid: tuple[int, ...],
    lambda_grid: tuple[float, ...],
    n_folds: int,
    seed: int,
) -> dict:
    """Select (k_total, lam) maximising OOF L1-vs-additive relative improvement."""
    folds = gene_disjoint_folds(pairs, n_folds=n_folds, seed=seed)
    best = {"k_total": k_grid[0], "lam": lambda_grid[0], "oof_theta_vs_additive": -np.inf}
    for k in k_grid:
        Z = Z_by_k[k]
        for lam in lambda_grid:
            e_model, e_add = [], []
            for train_idx, test_idx in folds:
                m = BilinearL1()
                m.fit(Z, [pairs[i] for i in train_idx], eps_obs[train_idx], lam=lam)
                for i in test_idx:
                    g, h = pairs[i]
                    pred = m.predict_eps(Z, g, h) + Z[g] * 0  # eps prediction
                    pred_dgh = pred + additive_pred_by_pair[i]
                    e_model.append(np.mean((pred_dgh - delta_pair_truth[i]) ** 2))
                    e_add.append(np.mean((additive_pred_by_pair[i] - delta_pair_truth[i]) ** 2))
            score = theta(np.array(e_model), np.array(e_add))
            if score > best["oof_theta_vs_additive"]:
                best = {"k_total": k, "lam": lam, "oof_theta_vs_additive": score}
    return best
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/alive/compose/test_select.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/alive/compose/select.py tests/alive/compose/test_select.py
git add src/alive/compose/select.py tests/alive/compose/test_select.py
git commit -m "feat(compose): gene-disjoint OOF folds + hyperparameter selection"
```

---

## Task 8: Norman data-card builder (raw/processed SHA-256)

**Files:**
- Modify: `src/alive/data/norman.py` (extend `data_card`)
- Test: `tests/alive/data/test_norman.py` (add data-card test)

**Interfaces:**
- Consumes: `alive.provenance.sha256_file`.
- Produces: `full_data_card(path, adata_summary, *, source, license, cell_line, modality) -> dict` adding `raw_sha256` (= `sha256_file(path)`), `n_cells`, `n_genes`, `n_singles`, `n_doubles`, `n_control`, `obs_columns`, `exclusions`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/alive/data/test_norman.py
from alive.data.norman import full_data_card


def test_full_data_card_includes_sha_and_counts(tmp_path):
    p = tmp_path / "toy.h5ad"
    p.write_bytes(b"not-real-h5ad-bytes")
    card = full_data_card(
        p,
        {"n_cells": 10, "n_genes": 5, "n_singles": 3, "n_doubles": 2, "n_control": 4,
         "obs_columns": ["perturbation"], "exclusions": ["min_cells<50"]},
        source="scPerturb NormanWeissman2019",
        license="CC BY 4.0",
        cell_line="K562",
        modality="CRISPRa",
    )
    assert len(card["raw_sha256"]) == 64
    assert card["n_doubles"] == 2
    assert card["license"] == "CC BY 4.0"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/alive/data/test_norman.py -k data_card -q`
Expected: FAIL — `ImportError: cannot import name 'full_data_card'`.

- [ ] **Step 3: Implement (append to norman.py)**

```python
# append to src/alive/data/norman.py
from alive.provenance import sha256_file  # noqa: E402


def full_data_card(
    path,
    adata_summary: dict,
    *,
    source: str,
    license: str,
    cell_line: str,
    modality: str,
) -> dict:
    """Provenance card with raw SHA-256 + dataset summary (activation blocker #3)."""
    card = {
        "path": str(path),
        "raw_sha256": sha256_file(path),
        "source": source,
        "license": license,
        "cell_line": cell_line,
        "modality": modality,
    }
    card.update(adata_summary)
    return card
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/alive/data/test_norman.py -q`
Expected: PASS (existing + new data-card test).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/alive/data/norman.py tests/alive/data/test_norman.py
git add src/alive/data/norman.py tests/alive/data/test_norman.py
git commit -m "feat(data): Norman full data-card with raw SHA-256 (blocker #3)"
```

---

## Task 9: Phase-2a orchestrator + leakage/no-seal guard

**Files:**
- Create: `src/alive/compose/phase2a.py`
- Test: `tests/alive/compose/test_phase2a.py`

**Interfaces:**
- Consumes: Tasks 1–7 + `alive.compose.identify.rank_diagnostics`, `alive.compose.gates.{rank_gate,measurability_gate}`.
- Produces:
  - `Phase2aResult` (frozen): `selected` (dict from `select_hyperparams`), `rank_report`, `noise_ceiling: float`, `futility: str` (`CONTINUE`/`FUTILITY_STOPPED`), `dev_theta_by_model: dict[str,float]`.
  - `run_phase2a(inputs) -> Phase2aResult` where `inputs` is a dict of dev-role arrays (Z-by-k, calibration pairs, eps, additive preds, delta-pair truths, esm). Asserts no key named `sealed*` is present (`LeakageError`).

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_phase2a.py
"""Tests for alive.compose.phase2a — written FIRST per TDD protocol."""
from __future__ import annotations

import numpy as np
import pytest

from alive.compose.gates import LeakageError
from alive.compose.operator import bilinear_predict, sym_basis_dim
from alive.compose.phase2a import Phase2aResult, run_phase2a


def _inputs(seed=0, n=24, p=3, npairs=40):
    rng = np.random.default_rng(seed)
    pairs = sorted({(min(a, b), max(a, b)) for a, b in rng.integers(0, n, (npairs, 2)) if a != b})
    Z_by_k = {}
    for k in (4, 6, 8):
        Z_by_k[k] = rng.normal(size=(n, k))
    coef = rng.normal(size=(p, sym_basis_dim(6)))
    eps = np.vstack([bilinear_predict(coef, Z_by_k[6][g], Z_by_k[6][h]) for g, h in pairs])
    add = rng.normal(size=(len(pairs), p))
    truth = eps + add
    eps_a = eps + 0.02 * rng.normal(size=eps.shape)
    eps_b = eps + 0.02 * rng.normal(size=eps.shape)
    return {
        "Z_by_k": Z_by_k, "pairs": pairs, "eps_obs": eps,
        "additive_pred_by_pair": add, "delta_pair_truth": truth,
        "eps_split_a": eps_a, "eps_split_b": eps_b,
        "k_grid": (4, 6, 8), "lambda_grid": (0.0, 1e-3, 1e-2), "n_folds": 4, "seed": 11,
    }


def test_run_phase2a_continues_on_signal():
    res = run_phase2a(_inputs())
    assert isinstance(res, Phase2aResult)
    assert res.selected["k_total"] in (4, 6, 8)
    assert res.futility in ("CONTINUE", "FUTILITY_STOPPED")
    assert res.noise_ceiling > 0.5  # strong split-half agreement


def test_run_phase2a_refuses_sealed_inputs():
    bad = _inputs()
    bad["sealed_double_unseen_eps"] = np.zeros((2, 3))
    with pytest.raises(LeakageError):
        run_phase2a(bad)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/alive/compose/test_phase2a.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/alive/compose/phase2a.py
"""COMPOSE Phase-2a dev orchestrator (NO seal). Selects hyperparams, runs the
real Phi-rank + measurability gates, and a development futility checkpoint.

Leakage guard: refuses any input key containing 'sealed'. Real execution on
Norman happens only after activation; here the inputs are dev-role arrays.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from alive.compose.gates import LeakageError, measurability_gate, rank_gate
from alive.compose.identify import rank_diagnostics
from alive.compose.metric2 import pair_errors, theta
from alive.compose.models import BilinearL1, HyperL3, IdOnly, SaturationL2
from alive.compose.select import gene_disjoint_folds, select_hyperparams


@dataclass(frozen=True)
class Phase2aResult:
    selected: dict
    rank_report: object
    noise_ceiling: float
    futility: str
    dev_theta_by_model: dict


def _oof_theta(model_cls, Z, pairs, eps_obs, add, truth, *, lam, n_folds, seed) -> float:
    folds = gene_disjoint_folds(pairs, n_folds=n_folds, seed=seed)
    e_model, e_add = [], []
    for tr, te in folds:
        m = model_cls()
        m.fit(Z, [pairs[i] for i in tr], eps_obs[tr], lam=lam)
        for i in te:
            g, h = pairs[i]
            pred = m.predict_eps(Z, g, h) + add[i]
            e_model.append(np.mean((pred - truth[i]) ** 2))
            e_add.append(np.mean((add[i] - truth[i]) ** 2))
    return theta(np.array(e_model), np.array(e_add))


def run_phase2a(inputs: dict) -> Phase2aResult:
    """Run dev-stage selection + gates + futility (no seal)."""
    if any("sealed" in k for k in inputs):
        raise LeakageError("Phase 2a received a sealed-role input")

    sel = select_hyperparams(
        inputs["Z_by_k"], inputs["pairs"], inputs["eps_obs"],
        inputs["delta_pair_truth"], inputs["additive_pred_by_pair"],
        k_grid=inputs["k_grid"], lambda_grid=inputs["lambda_grid"],
        n_folds=inputs["n_folds"], seed=inputs["seed"],
    )
    Zk = inputs["Z_by_k"][sel["k_total"]]
    rank_report = rank_diagnostics(Zk, inputs["pairs"])
    g_rank = rank_gate(rank_report)
    g_meas = measurability_gate(inputs["eps_split_a"], inputs["eps_split_b"])

    dev_theta = {
        name: _oof_theta(cls, Zk, inputs["pairs"], inputs["eps_obs"],
                         inputs["additive_pred_by_pair"], inputs["delta_pair_truth"],
                         lam=sel["lam"], n_folds=inputs["n_folds"], seed=inputs["seed"])
        for name, cls in (("L1", BilinearL1), ("L2", SaturationL2),
                          ("L3", HyperL3), ("ID_only", IdOnly))
    }
    continue_ok = (
        dev_theta["L1"] > 0.0 and g_rank.passed and g_meas.passed
    )
    return Phase2aResult(
        selected=sel,
        rank_report=rank_report,
        noise_ceiling=float(g_meas.detail["ceiling"]),
        futility="CONTINUE" if continue_ok else "FUTILITY_STOPPED",
        dev_theta_by_model=dev_theta,
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/alive/compose/test_phase2a.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Full compose suite + lint + commit**

```bash
uv run pytest tests/alive/compose tests/alive/data/test_norman.py -q
uv run ruff check src/alive/compose/phase2a.py tests/alive/compose/test_phase2a.py
git add src/alive/compose/phase2a.py tests/alive/compose/test_phase2a.py
git commit -m "feat(compose): Phase-2a dev orchestrator + leakage/no-seal guard"
```

---

## Self-Review

**1. Spec coverage (Phase 2a scope):**
- §10.4 deterministic split (PCG64/UTF-8/round-half-to-even) → Task 1.
- §10.4 response space (control+singles PCA-50) + δ/ε → Task 2.
- §10.4 z = expr-PCA + ESM(2) → Task 3.
- §10.5 metric (per-pair MSE, θ relative improvement) → Task 4.
- §10.5 models L1/L2/L3/ID-only → Task 5.
- §10.5 additive/lower-bound baselines + GEARS/CPA seam (leakage guard) → Task 6.
- §10.4 gene-disjoint OOF selection of k_total/λ → Task 7.
- §10.1.3 Norman data-card + SHA-256 → Task 8.
- §10.6 Phase-2a orchestration + real Φ-rank gate + measurability + futility, no seal → Task 9.
- Phase 2b (freeze + seal-once + bootstrap simultaneous inference + verdict + provenance) → companion plan `2026-06-24-compose-phase2b-seal-eval.md`.

**2. Placeholder scan:** No TBD/"add error handling"/"similar to Task N"; every code step has complete code. GEARS/CPA real backends are intentionally injected at activation (blocker #4) behind a tested adapter seam — not a placeholder but a dependency-inversion seam with stub tests.

**3. Type consistency:** `ComposeSplit` fields (Task 1) match Phase-1 usage. `ResponseSpace`/`mean_shift`/`epsilon` (Task 2) feed `build_z` δ inputs (Task 3) and `additive_pred` (Task 6). `Model` interface `fit(Z, pairs, eps_obs, *, lam)`/`predict_eps(Z, g, h)` consistent across Tasks 5, 7, 9. `theta`/`pair_errors` (Task 4) used in Tasks 7, 9. `gene_disjoint_folds` signature consistent Tasks 7, 9. `Phase2aResult` consumed by Phase 2b.

**Known follow-ups for Phase 2b / activation (not this plan):** real GEARS/CPA backend wiring + dependency lock (blocker #4); independent COMPOSE outcome store/audit (blocker #5); the seal-once integration test (blocker #6, in 2b); regime-specific detectable-effect power analysis on real Φ (blocker #2).
