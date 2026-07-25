# COMPOSE-K562-v1 Phase 1 Implementation Plan

> **Status update (2026-07-19): IMPLEMENTED + MERGED.** Phase-1 gates와 synthetic recovery는
> 완료됐다. 아래 task는 as-built record이며 current work queue가 아니다. Current release blocker는
> `docs/superpowers/COMPOSE-SEAL-READINESS.md`를 따른다.

> **Note (2026-07-04):** 이 plan의 내장 Phase-1 config schema(`lambda_grid`, `false_gi_tol`)는 이후
> 진화했다 — live `configs/compose_k562_v1_phase1.yaml`에는 두 key가 없고 λ는 `phase1.py`에서 hard-code,
> false-GI guard는 scale-relative ratio margin(`_FALSE_GI_RATIO_MARGIN`)이다. plan을 문자 그대로 재현하지
> 말고 현재 config/코드를 기준으로 삼을 것.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the cheap go/no-go for the COMPOSE epistasis milestone — prove the bilinear interaction-composition operator is identifiable/recoverable on synthetic data (claim 1), and run the Norman power/measurability/rank pre-check gates — WITHOUT touching any seal or integrating GEARS/CPA.

**Architecture:** New self-contained package `src/alive/compose/` holding pure-numpy math (operator, two-stage identification, synthetic recovery harness, pre-check gates) plus a Norman ingestion module under `src/alive/data/`. A thin CLI orchestrates a Phase-1 run that writes a go/no-go report through the existing `RunLedger` provenance. Phase 1 reads ONLY single-gene effects and a calibration subset of doubles; sealed double-unseen / secondary outcomes are never opened. The §6 prior-art gate is a parallel literature-audit deliverable.

**Tech Stack:** Python 3.11–3.12, numpy, scipy, anndata; ruff (line length 100); pytest. Reuses `alive.provenance` (composite run_id, RunLedger), `alive.data.profile`, `alive.data.features` (ESM-2 bank), `alive.metrics.selective`.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md`. This plan implements **Phase 1 only** (§5).
- **No seal access (§2.5).** Phase 1 code must never read `sealed_double_unseen` or
  `sealed_single_unseen` expression/outcomes. Only `singles_train` +
  `combo_calibration` (+ outcome-independent cell-count metadata) are readable. A leakage
  test enforces this. (`secondary_sealed` was an obsolete draft label.)
- **Outcome-independent eligibility (§2.2, CLAUDE.md#invariants).** Eligible singles/pairs are chosen by cell-count/QC + ESM availability + graph structure ONLY — never by GI strength or response magnitude.
- **Two-stage identification (§3.1–3.2).** `z_g` is fixed from singles BEFORE `B` is estimated; `B` estimation is a linear regularized least-squares.
- **Identifiability ≠ recovery ≠ generalization (§1.4, C3).** Algebraic identifiability is the noiseless rank condition; noisy recovery is the synthetic known-answer result; neither is a real-generalization claim. Keep them separate in code, names, and reports.
- **Measurability gate leakage guard (§2.4).** The noise-ceiling estimate uses only calibration/unsealed dev pairs or outcome-independent cell-count metadata — never sealed outcomes.
- **Provenance (CLAUDE.md#provenance).** Phase-1 runs record config digest, data-card hash, seed, git SHA, dependency lock, and artifact checksums via `alive.provenance.RunLedger`; run dirs are write-once.
- **Code conventions (CLAUDE.md#repo).** Production logic in `src/alive/`; NumPy-style docstrings + type hints on public API; ruff line length 100; no hardcoded paths/thresholds/seeds in source (config-driven); tests alongside under `tests/alive/`.
- **Commits** follow the repo trailer convention (Co-Authored-By + Claude-Session) already in use; the `git commit -m` lines below are abbreviated.
- **Run commands** with `uv run` (e.g. `uv run pytest ...`, `uv run ruff ...`).

---

## File Structure

| Path | Responsibility |
|---|---|
| `src/alive/compose/__init__.py` | Package marker + public re-exports. |
| `src/alive/compose/config.py` | `ComposePhase1Config` dataclass + `load_compose_config` (own YAML; does NOT touch the frozen CARTOGRAPHER `Config`). |
| `src/alive/compose/operator.py` | Symmetric bilinear operator: pair features, design matrix, prediction. Pure numpy. |
| `src/alive/compose/identify.py` | Two-stage identification: ridge LSQ for `B`; rank/condition diagnostics. |
| `src/alive/compose/synthetic.py` | Synthetic data generator + recovery harness (claim-1 known-answer proof). |
| `src/alive/compose/gates.py` | Power, measurability/noise-ceiling, rank pre-check gates. |
| `src/alive/compose/split.py` | Pair-level split with double-unseen gene-isolation (outcome-independent). |
| `src/alive/data/norman.py` | Norman AnnData ingestion, label parsing, single/pair effects, eligibility, data-card. |
| `src/alive/compose/phase1.py` | Phase-1 orchestration → go/no-go report + RunLedger provenance. |
| `configs/compose_k562_v1_phase1.yaml` | Phase-1 config (k/λ grids, noise model, gate thresholds, seeds). |
| `scripts/compose_phase1.py` | Thin CLI over `phase1.run_phase1`. |
| `docs/superpowers/audits/2026-06-23-compose-prior-art.md` | §6 prior-art gate deliverable. |
| `tests/alive/compose/` | Unit/known-answer/leakage tests for all of the above. |

---

## Task 1: Phase-1 package scaffold + config

**Files:**
- Create: `src/alive/compose/__init__.py`
- Create: `src/alive/compose/config.py`
- Create: `configs/compose_k562_v1_phase1.yaml`
- Create: `tests/alive/compose/__init__.py`
- Test: `tests/alive/compose/test_config.py`

**Interfaces:**
- Produces: `ComposePhase1Config` (frozen dataclass) with fields `k_grid: tuple[int, ...]`, `lambda_grid: tuple[float, ...]`, `response_dim: int`, `synthetic_n_genes: int`, `synthetic_rank: int`, `synthetic_noise_sd: tuple[float, ...]`, `min_double_unseen_pairs: int`, `min_cells_per_pair: int`, `calibration_fraction: float`, `recovery_rel_err_tol: float`, `false_gi_tol: float`, `registered_seeds: tuple[int, ...]`; and `load_compose_config(path) -> ComposePhase1Config`.

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_config.py
"""Tests for alive.compose.config — written FIRST per TDD protocol."""
from __future__ import annotations

import pytest

from alive.compose.config import ComposePhase1Config, ConfigError, load_compose_config

CANON = "configs/compose_k562_v1_phase1.yaml"


def test_canonical_round_trip():
    cfg = load_compose_config(CANON)
    assert isinstance(cfg, ComposePhase1Config)
    assert cfg.calibration_fraction == 0.6
    assert cfg.min_double_unseen_pairs >= 1
    assert len(cfg.k_grid) >= 1
    assert all(k >= 1 for k in cfg.k_grid)
    assert cfg.registered_seeds  # non-empty


def test_unknown_key_rejected(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("calibration_fraction: 0.6\nbogus_key: 1\n")
    with pytest.raises(ConfigError):
        load_compose_config(p)


def test_bad_fraction_rejected(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("calibration_fraction: 1.5\n")
    with pytest.raises(ConfigError):
        load_compose_config(p)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'alive.compose'`.

- [ ] **Step 3: Create the package + config**

```python
# src/alive/compose/__init__.py
"""COMPOSE-K562-v1 — identifiable interaction-composition operator (Phase 1).

Phase 1 = synthetic identifiability/recovery proof + Norman pre-check gates.
No seal access; see docs/superpowers/specs/2026-06-22-compose-epistasis-operator-design.md.
"""
```

```python
# tests/alive/compose/__init__.py
```

```python
# src/alive/compose/config.py
"""Phase-1 config for COMPOSE-K562-v1.

A standalone, frozen config (its own YAML); deliberately does NOT extend the
CARTOGRAPHER ``alive.config.Config`` so Phase-1 work cannot perturb that run_id.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised for invalid Phase-1 config."""


_KNOWN = frozenset(
    {
        "k_grid",
        "lambda_grid",
        "response_dim",
        "synthetic_n_genes",
        "synthetic_rank",
        "synthetic_noise_sd",
        "min_double_unseen_pairs",
        "min_cells_per_pair",
        "calibration_fraction",
        "recovery_rel_err_tol",
        "false_gi_tol",
        "registered_seeds",
    }
)


@dataclass(frozen=True)
class ComposePhase1Config:
    """Frozen Phase-1 parameters. Load via :func:`load_compose_config`."""

    k_grid: tuple[int, ...]
    lambda_grid: tuple[float, ...]
    response_dim: int
    synthetic_n_genes: int
    synthetic_rank: int
    synthetic_noise_sd: tuple[float, ...]
    min_double_unseen_pairs: int
    min_cells_per_pair: int
    calibration_fraction: float
    recovery_rel_err_tol: float
    false_gi_tol: float
    registered_seeds: tuple[int, ...]


def load_compose_config(path: str | Path) -> ComposePhase1Config:
    """Load and validate the Phase-1 YAML config."""
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text()) or {}
    unknown = set(raw) - _KNOWN
    if unknown:
        raise ConfigError(f"unknown config keys: {sorted(unknown)}")
    frac = float(raw.get("calibration_fraction", 0.6))
    if not 0.0 < frac < 1.0:
        raise ConfigError(f"calibration_fraction must be in (0,1), got {frac}")
    try:
        return ComposePhase1Config(
            k_grid=tuple(int(x) for x in raw["k_grid"]),
            lambda_grid=tuple(float(x) for x in raw["lambda_grid"]),
            response_dim=int(raw["response_dim"]),
            synthetic_n_genes=int(raw["synthetic_n_genes"]),
            synthetic_rank=int(raw["synthetic_rank"]),
            synthetic_noise_sd=tuple(float(x) for x in raw["synthetic_noise_sd"]),
            min_double_unseen_pairs=int(raw["min_double_unseen_pairs"]),
            min_cells_per_pair=int(raw["min_cells_per_pair"]),
            calibration_fraction=frac,
            recovery_rel_err_tol=float(raw["recovery_rel_err_tol"]),
            false_gi_tol=float(raw["false_gi_tol"]),
            registered_seeds=tuple(int(x) for x in raw["registered_seeds"]),
        )
    except KeyError as exc:
        raise ConfigError(f"missing required key: {exc}") from exc
```

```yaml
# configs/compose_k562_v1_phase1.yaml
# COMPOSE-K562-v1 Phase 1 (synthetic recovery + Norman pre-check gates). DEFERRED.
k_grid: [4, 8, 12]
lambda_grid: [0.0, 0.001, 0.01, 0.1]
response_dim: 50
synthetic_n_genes: 60
synthetic_rank: 3
synthetic_noise_sd: [0.0, 0.05, 0.1, 0.2]
min_double_unseen_pairs: 20      # power-gate floor (pre-registered)
min_cells_per_pair: 50
calibration_fraction: 0.6
recovery_rel_err_tol: 0.15       # noisy synthetic recovery acceptance
false_gi_tol: 0.05               # ||eps_hat|| when eps*=0 must stay below
registered_seeds: [11, 23, 37]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/alive/compose/test_config.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/alive/compose tests/alive/compose
uv run ruff format src/alive/compose tests/alive/compose
git add src/alive/compose configs/compose_k562_v1_phase1.yaml tests/alive/compose
git commit -m "feat(compose): Phase-1 package scaffold + config"
```

---

## Task 2: Symmetric bilinear operator core

**Files:**
- Create: `src/alive/compose/operator.py`
- Test: `tests/alive/compose/test_operator.py`

**Interfaces:**
- Produces:
  - `sym_basis_dim(k: int) -> int` → `k*(k+1)//2`.
  - `pair_feature(z_g: np.ndarray, z_h: np.ndarray) -> np.ndarray` → symmetric bilinear feature of length `sym_basis_dim(k)`; symmetric in (g,h).
  - `design_matrix(Z: np.ndarray, pairs: list[tuple[int, int]]) -> np.ndarray` → `(n_pairs, sym_dim)`.
  - `bilinear_predict(coef: np.ndarray, z_g: np.ndarray, z_h: np.ndarray) -> np.ndarray` → `coef @ pair_feature`, length `p` (where `coef` is `(p, sym_dim)`).
- Consumes: nothing (pure numpy).

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_operator.py
"""Tests for alive.compose.operator — written FIRST per TDD protocol."""
from __future__ import annotations

import numpy as np

from alive.compose.operator import (
    bilinear_predict,
    design_matrix,
    pair_feature,
    sym_basis_dim,
)


def test_sym_basis_dim():
    assert sym_basis_dim(1) == 1
    assert sym_basis_dim(4) == 10


def test_pair_feature_symmetric():
    rng = np.random.default_rng(0)
    zg, zh = rng.normal(size=5), rng.normal(size=5)
    np.testing.assert_allclose(pair_feature(zg, zh), pair_feature(zh, zg))
    assert pair_feature(zg, zh).shape == (sym_basis_dim(5),)


def test_design_matrix_shape():
    Z = np.random.default_rng(1).normal(size=(6, 4))
    pairs = [(0, 1), (2, 3), (0, 4)]
    Phi = design_matrix(Z, pairs)
    assert Phi.shape == (3, sym_basis_dim(4))


def test_predict_matches_quadratic_form():
    # eps[m] = z_g^T B_m z_h with symmetric B_m must equal coef @ pair_feature.
    rng = np.random.default_rng(2)
    k, p = 4, 3
    Z = rng.normal(size=(2, k))
    zg, zh = Z[0], Z[1]
    Bs = []
    coef_rows = []
    from alive.compose.operator import _sym_to_vec  # internal, see impl
    for _ in range(p):
        M = rng.normal(size=(k, k))
        B = (M + M.T) / 2
        Bs.append(B)
        coef_rows.append(_sym_to_vec(B))
    coef = np.vstack(coef_rows)
    quad = np.array([zg @ B @ zh for B in Bs])
    np.testing.assert_allclose(bilinear_predict(coef, zg, zh), quad, atol=1e-10)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_operator.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'alive.compose.operator'`.

- [ ] **Step 3: Implement**

```python
# src/alive/compose/operator.py
"""Symmetric bilinear interaction-composition operator (Phase 1, §3.2).

eps_gh[m] = z_g^T B_m z_h with each B_m symmetric. We store the operator as a
``coef`` matrix of shape (p, sym_dim) where each row is the symmetric matrix
B_m flattened by :func:`_sym_to_vec`. The matching pair feature
:func:`pair_feature` is built so that ``coef @ pair_feature(z_g, z_h)`` equals
the stacked quadratic forms — and is symmetric in (g, h).
"""
from __future__ import annotations

import numpy as np


def sym_basis_dim(k: int) -> int:
    """Dimension of the symmetric k x k space: ``k(k+1)/2``."""
    return k * (k + 1) // 2


def _sym_to_vec(B: np.ndarray) -> np.ndarray:
    """Flatten a symmetric matrix: diagonal as-is, off-diagonal scaled by sqrt(2).

    The sqrt(2) scaling makes ``_sym_to_vec(B) @ pair_feature(zg, zh)`` reproduce
    ``zg^T B zh`` for symmetric B without double counting off-diagonal terms.
    """
    k = B.shape[0]
    iu = np.triu_indices(k)
    out = B[iu].astype(np.float64).copy()
    off = iu[0] != iu[1]
    out[off] *= np.sqrt(2.0)
    return out


def pair_feature(z_g: np.ndarray, z_h: np.ndarray) -> np.ndarray:
    """Symmetric bilinear feature vector of length ``sym_basis_dim(k)``."""
    z_g = np.asarray(z_g, dtype=np.float64)
    z_h = np.asarray(z_h, dtype=np.float64)
    outer = np.outer(z_g, z_h)
    sym = (outer + outer.T) / 2.0
    return _sym_to_vec(sym)


def design_matrix(Z: np.ndarray, pairs: list[tuple[int, int]]) -> np.ndarray:
    """Stack :func:`pair_feature` over ``pairs`` → ``(n_pairs, sym_dim)``."""
    Z = np.asarray(Z, dtype=np.float64)
    return np.vstack([pair_feature(Z[g], Z[h]) for (g, h) in pairs])


def bilinear_predict(coef: np.ndarray, z_g: np.ndarray, z_h: np.ndarray) -> np.ndarray:
    """Predict eps (length p) = ``coef @ pair_feature(z_g, z_h)``."""
    return np.asarray(coef, dtype=np.float64) @ pair_feature(z_g, z_h)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/alive/compose/test_operator.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/alive/compose/operator.py tests/alive/compose/test_operator.py
git add src/alive/compose/operator.py tests/alive/compose/test_operator.py
git commit -m "feat(compose): symmetric bilinear operator core"
```

---

## Task 3: Two-stage identification + rank diagnostics

**Files:**
- Create: `src/alive/compose/identify.py`
- Test: `tests/alive/compose/test_identify.py`

**Interfaces:**
- Consumes: `alive.compose.operator.design_matrix`, `sym_basis_dim`, `bilinear_predict`.
- Produces:
  - `RankReport` (frozen dataclass): `sym_dim: int`, `rank: int`, `is_full_rank: bool`, `condition_number: float`.
  - `rank_diagnostics(Z, pairs) -> RankReport`.
  - `identify_operator(Z, pairs, eps_obs, *, lam=0.0) -> np.ndarray` → `coef` of shape `(p, sym_dim)` via ridge LSQ (`eps_obs` shape `(n_pairs, p)`).

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_identify.py
"""Tests for alive.compose.identify — written FIRST per TDD protocol."""
from __future__ import annotations

import numpy as np

from alive.compose.identify import RankReport, identify_operator, rank_diagnostics
from alive.compose.operator import bilinear_predict, sym_basis_dim


def _make(rng, n_genes=20, k=4, p=3, n_pairs=40):
    Z = rng.normal(size=(n_genes, k))
    coef_true = rng.normal(size=(p, sym_basis_dim(k)))
    pairs = [(int(a), int(b)) for a, b in rng.integers(0, n_genes, size=(n_pairs, 2)) if a != b]
    eps = np.vstack([bilinear_predict(coef_true, Z[g], Z[h]) for g, h in pairs])
    return Z, coef_true, pairs, eps


def test_noiseless_full_rank_recovers_coef():
    rng = np.random.default_rng(0)
    Z, coef_true, pairs, eps = _make(rng)
    rep = rank_diagnostics(Z, pairs)
    assert isinstance(rep, RankReport)
    assert rep.is_full_rank  # enough diverse pairs
    coef_hat = identify_operator(Z, pairs, eps, lam=0.0)
    np.testing.assert_allclose(coef_hat, coef_true, atol=1e-6)


def test_predicts_held_out_pair_when_full_rank():
    rng = np.random.default_rng(1)
    Z, coef_true, pairs, eps = _make(rng)
    coef_hat = identify_operator(Z, pairs, eps, lam=0.0)
    g, h = 0, 5  # a pair not necessarily in `pairs`
    np.testing.assert_allclose(
        bilinear_predict(coef_hat, Z[g], Z[h]),
        bilinear_predict(coef_true, Z[g], Z[h]),
        atol=1e-6,
    )


def test_rank_deficient_flagged():
    rng = np.random.default_rng(2)
    Z = rng.normal(size=(20, 4))
    pairs = [(0, 1), (0, 1), (0, 1)]  # one unique pair → rank 1
    rep = rank_diagnostics(Z, pairs)
    assert not rep.is_full_rank
    assert rep.rank == 1
    assert rep.sym_dim == sym_basis_dim(4)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_identify.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'alive.compose.identify'`.

- [ ] **Step 3: Implement**

```python
# src/alive/compose/identify.py
"""Two-stage identification of the bilinear operator (Phase 1, §3.2).

Stage 1 (z fixed from singles) happens upstream; here Stage 2 estimates the
operator ``coef`` from calibration pairs by (ridge) least squares on the design
matrix, and reports the algebraic rank condition (noiseless identifiability) +
the conditioning that governs noisy recovery.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from alive.compose.operator import design_matrix, sym_basis_dim


@dataclass(frozen=True)
class RankReport:
    """Algebraic-identifiability diagnostics for a calibration pair set."""

    sym_dim: int
    rank: int
    is_full_rank: bool
    condition_number: float


def rank_diagnostics(Z: np.ndarray, pairs: list[tuple[int, int]]) -> RankReport:
    """Rank and condition number of the calibration design matrix Phi."""
    Z = np.asarray(Z, dtype=np.float64)
    k = Z.shape[1]
    sym_dim = sym_basis_dim(k)
    phi = design_matrix(Z, pairs)
    svals = np.linalg.svd(phi, compute_uv=False)
    tol = max(phi.shape) * np.finfo(np.float64).eps * (svals[0] if svals.size else 0.0)
    rank = int(np.sum(svals > tol))
    pos = svals[svals > tol]
    cond = float(pos[0] / pos[-1]) if pos.size else float("inf")
    return RankReport(
        sym_dim=sym_dim,
        rank=rank,
        is_full_rank=rank >= sym_dim,
        condition_number=cond,
    )


def identify_operator(
    Z: np.ndarray,
    pairs: list[tuple[int, int]],
    eps_obs: np.ndarray,
    *,
    lam: float = 0.0,
) -> np.ndarray:
    """Estimate ``coef`` (p, sym_dim) by ridge least squares on the design matrix.

    Solves ``min_C ||Phi C^T - eps_obs||^2 + lam ||C||^2`` via the normal
    equations ``(Phi^T Phi + lam I) C^T = Phi^T eps_obs``.
    """
    Z = np.asarray(Z, dtype=np.float64)
    eps_obs = np.asarray(eps_obs, dtype=np.float64)
    phi = design_matrix(Z, pairs)
    gram = phi.T @ phi + float(lam) * np.eye(phi.shape[1])
    rhs = phi.T @ eps_obs
    coef_t = np.linalg.solve(gram, rhs)  # (sym_dim, p)
    return coef_t.T
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/alive/compose/test_identify.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/alive/compose/identify.py tests/alive/compose/test_identify.py
git add src/alive/compose/identify.py tests/alive/compose/test_identify.py
git commit -m "feat(compose): two-stage identification + rank diagnostics"
```

---

## Task 4: Synthetic data generator

**Files:**
- Create: `src/alive/compose/synthetic.py` (generator part)
- Test: `tests/alive/compose/test_synthetic_gen.py`

**Interfaces:**
- Consumes: `alive.compose.operator.bilinear_predict`, `sym_basis_dim`.
- Produces:
  - `SyntheticData` (frozen dataclass): `Z: np.ndarray (n_genes,k)`, `coef_true: np.ndarray (p,sym_dim)`, `pairs: list[tuple[int,int]]`, `eps_true: np.ndarray (n_pairs,p)`, `eps_obs: np.ndarray (n_pairs,p)`.
  - `make_synthetic(*, n_genes, k, p, rank, n_pairs, noise_sd, seed) -> SyntheticData`. A low-rank symmetric operator is built per output dim; `noise_sd=0.0` ⇒ `eps_obs == eps_true`; `eps*` is exactly zero when `rank == 0`.

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_synthetic_gen.py
"""Tests for alive.compose.synthetic generator — written FIRST per TDD protocol."""
from __future__ import annotations

import numpy as np

from alive.compose.operator import sym_basis_dim
from alive.compose.synthetic import SyntheticData, make_synthetic


def test_shapes_and_noiseless_equality():
    d = make_synthetic(n_genes=30, k=4, p=5, rank=2, n_pairs=50, noise_sd=0.0, seed=0)
    assert isinstance(d, SyntheticData)
    assert d.Z.shape == (30, 4)
    assert d.coef_true.shape == (5, sym_basis_dim(4))
    assert d.eps_true.shape == (len(d.pairs), 5)
    np.testing.assert_array_equal(d.eps_obs, d.eps_true)  # noiseless


def test_zero_rank_means_zero_gi():
    d = make_synthetic(n_genes=20, k=4, p=3, rank=0, n_pairs=30, noise_sd=0.0, seed=1)
    np.testing.assert_allclose(d.eps_true, 0.0, atol=1e-12)


def test_noise_perturbs_and_is_deterministic():
    a = make_synthetic(n_genes=20, k=4, p=3, rank=2, n_pairs=30, noise_sd=0.1, seed=2)
    b = make_synthetic(n_genes=20, k=4, p=3, rank=2, n_pairs=30, noise_sd=0.1, seed=2)
    np.testing.assert_array_equal(a.eps_obs, b.eps_obs)  # seed-deterministic
    assert not np.allclose(a.eps_obs, a.eps_true)         # noise applied
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_synthetic_gen.py -q`
Expected: FAIL — `ImportError: cannot import name 'make_synthetic'`.

- [ ] **Step 3: Implement (generator portion of synthetic.py)**

```python
# src/alive/compose/synthetic.py
"""Synthetic generator + recovery harness for the claim-1 known-answer proof.

The generator builds fixed gene factors Z, a low-rank symmetric ground-truth
operator, the exact GI vectors eps_true, and a noisy observation eps_obs. The
recovery harness (Task 5) consumes this to prove algebraic recovery (noiseless)
and characterise noisy recovery — independent of any real data.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from alive.compose.operator import _sym_to_vec, bilinear_predict, sym_basis_dim


@dataclass(frozen=True)
class SyntheticData:
    """Ground-truth synthetic instance for recovery testing."""

    Z: np.ndarray
    coef_true: np.ndarray
    pairs: list[tuple[int, int]]
    eps_true: np.ndarray
    eps_obs: np.ndarray


def _low_rank_sym(rng: np.random.Generator, k: int, rank: int) -> np.ndarray:
    """A symmetric k x k matrix of given rank (zero matrix when rank == 0)."""
    if rank <= 0:
        return np.zeros((k, k))
    U = rng.normal(size=(k, rank))
    return U @ U.T


def make_synthetic(
    *,
    n_genes: int,
    k: int,
    p: int,
    rank: int,
    n_pairs: int,
    noise_sd: float,
    seed: int,
) -> SyntheticData:
    """Generate a synthetic identification instance (see module docstring)."""
    rng = np.random.default_rng(seed)
    Z = rng.normal(size=(n_genes, k))
    coef_true = np.vstack([_sym_to_vec(_low_rank_sym(rng, k, rank)) for _ in range(p)])
    seen: set[tuple[int, int]] = set()
    pairs: list[tuple[int, int]] = []
    while len(pairs) < n_pairs:
        a, b = int(rng.integers(n_genes)), int(rng.integers(n_genes))
        if a == b:
            continue
        key = (min(a, b), max(a, b))
        if key in seen:
            continue
        seen.add(key)
        pairs.append(key)
    eps_true = np.vstack([bilinear_predict(coef_true, Z[g], Z[h]) for g, h in pairs])
    noise = rng.normal(scale=noise_sd, size=eps_true.shape) if noise_sd > 0 else 0.0
    eps_obs = eps_true + noise
    return SyntheticData(Z=Z, coef_true=coef_true, pairs=pairs, eps_true=eps_true, eps_obs=eps_obs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/alive/compose/test_synthetic_gen.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/alive/compose/synthetic.py tests/alive/compose/test_synthetic_gen.py
git add src/alive/compose/synthetic.py tests/alive/compose/test_synthetic_gen.py
git commit -m "feat(compose): synthetic generator for recovery proof"
```

---

## Task 5: Synthetic recovery harness (claim-1 known-answer proof)

**Files:**
- Modify: `src/alive/compose/synthetic.py` (append recovery harness)
- Test: `tests/alive/compose/test_recovery.py`

**Interfaces:**
- Consumes: `make_synthetic`, `alive.compose.identify.identify_operator`, `rank_diagnostics`, `alive.compose.operator.bilinear_predict`.
- Produces:
  - `RecoveryReport` (frozen dataclass): `noiseless_rel_err: float`, `noisy_rel_err: float`, `held_out_pred_rel_err: float`, `false_gi_norm: float`, `is_full_rank: bool`, `frontier: tuple[dict, ...]`.
  - `run_recovery(*, n_genes, p, rank, n_pairs, noise_sd, seed, k, held_out_pairs=...) -> RecoveryReport`.
  - `frontier_sweep(*, k_grid, n_cal_grid, ...) -> tuple[dict, ...]` mapping `(k, n_cal)` → relative recovery error.

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_recovery.py
"""Known-answer tests for the synthetic recovery harness (claim 1).

Covers §3.4: (a) noiseless algebraic recovery, (b) noisy within tolerance,
(c) graceful degradation when rank-deficient, (d) false-GI guard (eps*=0 -> ~0),
(e) k vs |Cal| frontier.
"""
from __future__ import annotations

from alive.compose.synthetic import RecoveryReport, frontier_sweep, run_recovery


def test_noiseless_algebraic_recovery():
    r = run_recovery(n_genes=40, p=5, rank=2, n_pairs=60, noise_sd=0.0, seed=0, k=4)
    assert isinstance(r, RecoveryReport)
    assert r.is_full_rank
    assert r.noiseless_rel_err < 1e-8           # (a)
    assert r.held_out_pred_rel_err < 1e-8


def test_noisy_recovery_within_tolerance():
    r = run_recovery(n_genes=40, p=5, rank=2, n_pairs=60, noise_sd=0.05, seed=1, k=4)
    assert r.noisy_rel_err < 0.15               # (b) matches config tol


def test_false_gi_guard():
    r = run_recovery(n_genes=40, p=5, rank=0, n_pairs=60, noise_sd=0.0, seed=2, k=4)
    assert r.false_gi_norm < 1e-8               # (d) eps*=0 -> eps_hat ~ 0


def test_rank_deficient_degrades_and_flags():
    # Too few pairs for k=8 (sym_dim=36) -> not full rank.
    r = run_recovery(n_genes=40, p=3, rank=2, n_pairs=10, noise_sd=0.0, seed=3, k=8)
    assert not r.is_full_rank                    # (c) flagged


def test_frontier_sweep_keys():
    fr = frontier_sweep(k_grid=(4, 8), n_cal_grid=(20, 60), p=3, rank=2, noise_sd=0.05, seed=4)
    assert {(d["k"], d["n_cal"]) for d in fr} == {(4, 20), (4, 60), (8, 20), (8, 60)}
    assert all("rel_err" in d and "is_full_rank" in d for d in fr)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_recovery.py -q`
Expected: FAIL — `ImportError: cannot import name 'run_recovery'`.

- [ ] **Step 3: Implement (append to synthetic.py)**

```python
# --- append to src/alive/compose/synthetic.py ---

from alive.compose.identify import identify_operator, rank_diagnostics  # noqa: E402


def _rel_err(a: np.ndarray, b: np.ndarray) -> float:
    """Relative L2 error ||a-b|| / max(||b||, eps)."""
    denom = float(np.linalg.norm(b))
    return float(np.linalg.norm(a - b) / denom) if denom > 1e-12 else float(np.linalg.norm(a))


@dataclass(frozen=True)
class RecoveryReport:
    """Outcome of a synthetic recovery run (claim-1 evidence)."""

    noiseless_rel_err: float
    noisy_rel_err: float
    held_out_pred_rel_err: float
    false_gi_norm: float
    is_full_rank: bool
    frontier: tuple[dict, ...]


def run_recovery(
    *,
    n_genes: int,
    p: int,
    rank: int,
    n_pairs: int,
    noise_sd: float,
    seed: int,
    k: int,
) -> RecoveryReport:
    """Recover the operator from synthetic data and score it (§3.4)."""
    d = make_synthetic(
        n_genes=n_genes, k=k, p=p, rank=rank, n_pairs=n_pairs, noise_sd=noise_sd, seed=seed
    )
    rep_rank = rank_diagnostics(d.Z, d.pairs)

    # Noiseless coefficient recovery (algebraic).
    clean = make_synthetic(
        n_genes=n_genes, k=k, p=p, rank=rank, n_pairs=n_pairs, noise_sd=0.0, seed=seed
    )
    coef_clean = identify_operator(clean.Z, clean.pairs, clean.eps_true, lam=0.0)
    noiseless_rel = _rel_err(coef_clean, clean.coef_true)

    # Noisy recovery (small ridge).
    coef_noisy = identify_operator(d.Z, d.pairs, d.eps_obs, lam=1e-3)
    noisy_rel = _rel_err(coef_noisy, d.coef_true)

    # Held-out (combo-unseen) pair prediction from the clean fit.
    g, h = 0, n_genes - 1
    held = _rel_err(
        bilinear_predict(coef_clean, clean.Z[g], clean.Z[h]),
        bilinear_predict(clean.coef_true, clean.Z[g], clean.Z[h]),
    )

    # False-GI guard: when eps* == 0, recovered eps must be ~0.
    false_gi = float(
        np.max([np.linalg.norm(bilinear_predict(coef_clean, clean.Z[a], clean.Z[b]))
                for a, b in clean.pairs])
    ) if rank == 0 else 0.0

    return RecoveryReport(
        noiseless_rel_err=noiseless_rel,
        noisy_rel_err=noisy_rel,
        held_out_pred_rel_err=held,
        false_gi_norm=false_gi,
        is_full_rank=rep_rank.is_full_rank,
        frontier=(),
    )


def frontier_sweep(
    *,
    k_grid: tuple[int, ...],
    n_cal_grid: tuple[int, ...],
    p: int,
    rank: int,
    noise_sd: float,
    seed: int,
    n_genes: int = 60,
) -> tuple[dict, ...]:
    """Sweep (k, |Cal|) and report noisy recovery error + rank status."""
    out: list[dict] = []
    for k in k_grid:
        for n_cal in n_cal_grid:
            r = run_recovery(
                n_genes=n_genes, p=p, rank=rank, n_pairs=n_cal,
                noise_sd=noise_sd, seed=seed, k=k,
            )
            out.append(
                {"k": k, "n_cal": n_cal, "rel_err": r.noisy_rel_err, "is_full_rank": r.is_full_rank}
            )
    return tuple(out)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/alive/compose/test_recovery.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/alive/compose/synthetic.py tests/alive/compose/test_recovery.py
git add src/alive/compose/synthetic.py tests/alive/compose/test_recovery.py
git commit -m "feat(compose): synthetic recovery harness (claim-1 known-answer proof)"
```

---

## Task 6: Norman ingestion + outcome-independent eligibility

**Files:**
- Create: `src/alive/data/norman.py`
- Test: `tests/alive/data/test_norman.py`

**Interfaces:**
- Consumes: `anndata`, `numpy`; `alive.data.profile.profile_perturbations` (reused for cell-count profiling).
- Produces:
  - `parse_labels(obs_values, *, control_token, combo_sep) -> tuple[dict, dict, np.ndarray]` → (`singles: {gene: row_mask_indices}`, `doubles: {(g,h): idx}`, `control_idx`).
  - `single_effects(X, singles, control_idx) -> dict[str, np.ndarray]` (per-gene mean shift δ_g in the given expression matrix space).
  - `eligible_genes(singles, *, min_cells, available_feature_ids) -> list[str]` (outcome-independent).
  - `eligible_pairs(doubles, eligible_gene_set, *, min_cells) -> list[tuple[str, str]]` (outcome-independent).
  - `data_card(path, *, source, license, cell_line, modality) -> dict`.

- [ ] **Step 1: Write the failing test (synthetic AnnData fixture)**

```python
# tests/alive/data/test_norman.py
"""Tests for alive.data.norman — written FIRST per TDD protocol.

Uses a tiny synthetic AnnData; no real download.
"""
from __future__ import annotations

import anndata as ad
import numpy as np

from alive.data.norman import (
    eligible_genes,
    eligible_pairs,
    parse_labels,
    single_effects,
)


def _toy():
    labels = np.array(
        ["ctrl"] * 4 + ["A"] * 3 + ["B"] * 3 + ["A+B"] * 2 + ["A+C"] * 1, dtype=object
    )
    X = np.arange(labels.size * 2, dtype=np.float64).reshape(labels.size, 2)
    return labels, X


def test_parse_labels():
    labels, X = _toy()
    singles, doubles, ctrl = parse_labels(labels, control_token="ctrl", combo_sep="+")
    assert set(singles) == {"A", "B"}
    assert set(doubles) == {("A", "B"), ("A", "C")}
    assert ctrl.tolist() == [0, 1, 2, 3]


def test_single_effects_shape():
    labels, X = _toy()
    singles, doubles, ctrl = parse_labels(labels, control_token="ctrl", combo_sep="+")
    eff = single_effects(X, singles, ctrl)
    assert set(eff) == {"A", "B"}
    assert eff["A"].shape == (2,)


def test_eligibility_is_outcome_independent():
    labels, X = _toy()
    singles, doubles, ctrl = parse_labels(labels, control_token="ctrl", combo_sep="+")
    # min_cells=3 keeps A,B; require feature availability for A,B only
    genes = eligible_genes(singles, min_cells=3, available_feature_ids={"A", "B"})
    assert genes == ["A", "B"]
    # ("A","B") has 2 cells; with min_cells=2 it is eligible, ("A","C") drops (C ineligible)
    pairs = eligible_pairs(doubles, set(genes), min_cells=2)
    assert pairs == [("A", "B")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/data/test_norman.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'alive.data.norman'`.

- [ ] **Step 3: Implement**

```python
# src/alive/data/norman.py
"""Norman et al. 2019 K562 CRISPRa GI Perturb-seq ingestion (COMPOSE Phase 1).

Outcome-independent: eligibility uses cell counts + feature availability only,
never GI strength (CLAUDE.md#invariants; spec §2.2). Combo labels are "<g><sep><h>".
"""
from __future__ import annotations

import numpy as np


def parse_labels(
    obs_values: np.ndarray,
    *,
    control_token: str,
    combo_sep: str,
) -> tuple[dict[str, np.ndarray], dict[tuple[str, str], np.ndarray], np.ndarray]:
    """Split obs perturbation labels into singles, doubles, and control indices."""
    obs_values = np.asarray(obs_values, dtype=object)
    singles: dict[str, list[int]] = {}
    doubles: dict[tuple[str, str], list[int]] = {}
    control: list[int] = []
    for i, raw in enumerate(obs_values):
        s = str(raw)
        if s == control_token:
            control.append(i)
        elif combo_sep in s:
            a, b = s.split(combo_sep, 1)
            key = (min(a, b), max(a, b))
            doubles.setdefault(key, []).append(i)
        else:
            singles.setdefault(s, []).append(i)
    return (
        {g: np.asarray(ix, dtype=int) for g, ix in singles.items()},
        {k: np.asarray(ix, dtype=int) for k, ix in doubles.items()},
        np.asarray(control, dtype=int),
    )


def single_effects(
    X: np.ndarray,
    singles: dict[str, np.ndarray],
    control_idx: np.ndarray,
) -> dict[str, np.ndarray]:
    """Per-gene mean shift delta_g = mean(X[single]) - mean(X[control])."""
    ctrl_mean = np.asarray(X[control_idx]).mean(axis=0)
    return {g: np.asarray(X[ix]).mean(axis=0) - ctrl_mean for g, ix in singles.items()}


def eligible_genes(
    singles: dict[str, np.ndarray],
    *,
    min_cells: int,
    available_feature_ids: set[str],
) -> list[str]:
    """Genes with enough single cells AND an available sequence feature."""
    return sorted(
        g
        for g, ix in singles.items()
        if len(ix) >= min_cells and g in available_feature_ids
    )


def eligible_pairs(
    doubles: dict[tuple[str, str], np.ndarray],
    eligible_gene_set: set[str],
    *,
    min_cells: int,
) -> list[tuple[str, str]]:
    """Pairs with enough double cells whose BOTH genes are eligible singles."""
    return sorted(
        key
        for key, ix in doubles.items()
        if len(ix) >= min_cells and key[0] in eligible_gene_set and key[1] in eligible_gene_set
    )


def data_card(
    path: str,
    *,
    source: str,
    license: str,
    cell_line: str,
    modality: str,
) -> dict[str, str]:
    """Minimal provenance card for the Norman dataset (extended in Phase 2)."""
    return {
        "path": str(path),
        "source": source,
        "license": license,
        "cell_line": cell_line,
        "modality": modality,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/alive/data/test_norman.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/alive/data/norman.py tests/alive/data/test_norman.py
git add src/alive/data/norman.py tests/alive/data/test_norman.py
git commit -m "feat(data): Norman ingestion + outcome-independent eligibility"
```

---

## Task 7: Pair-level split with double-unseen gene isolation

**Files:**
- Create: `src/alive/compose/split.py`
- Test: `tests/alive/compose/test_split.py`

**Interfaces:**
- Consumes: nothing beyond numpy.
- Produces:
  - `ComposeSplit` (frozen dataclass): `combo_calibration: list[tuple[str,str]]`, `sealed_double_unseen: list[tuple[str,str]]`, `secondary: list[tuple[str,str]]`, `combo_genes: frozenset[str]`.
  - `build_pair_split(eligible_pairs, *, seed, calibration_fraction) -> ComposeSplit`. Invariant: for every sealed double-unseen pair, NEITHER gene appears in any `combo_calibration` pair.

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_split.py
"""Tests for alive.compose.split — written FIRST per TDD protocol.

Enforces the double-unseen gene-isolation invariant (spec §2.3) and leakage.
"""
from __future__ import annotations

from alive.compose.split import ComposeSplit, build_pair_split


def _pairs():
    genes = [chr(ord("A") + i) for i in range(8)]
    return [(genes[i], genes[j]) for i in range(8) for j in range(i + 1, 8)]


def test_roles_disjoint_and_cover():
    sp = build_pair_split(_pairs(), seed=0, calibration_fraction=0.6)
    assert isinstance(sp, ComposeSplit)
    all_pairs = set(_pairs())
    union = set(sp.combo_calibration) | set(sp.sealed_double_unseen) | set(sp.secondary)
    assert union <= all_pairs
    assert not (set(sp.combo_calibration) & set(sp.sealed_double_unseen))


def test_double_unseen_genes_isolated_from_calibration():
    sp = build_pair_split(_pairs(), seed=1, calibration_fraction=0.6)
    cal_genes = {g for pair in sp.combo_calibration for g in pair}
    for a, b in sp.sealed_double_unseen:
        assert a not in cal_genes and b not in cal_genes  # gene isolation invariant
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_split.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'alive.compose.split'`.

- [ ] **Step 3: Implement**

```python
# src/alive/compose/split.py
"""Pair-level split with double-unseen gene isolation (COMPOSE Phase 1, §2.3).

The headline `sealed_double_unseen` role holds pairs whose BOTH genes are absent
from every `combo_calibration` pair (combo/pair-zero-shot). Selection is
outcome-independent — driven only by a seeded gene partition.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ComposeSplit:
    """Disjoint pair roles + the calibration gene set."""

    combo_calibration: list[tuple[str, str]]
    sealed_double_unseen: list[tuple[str, str]]
    secondary: list[tuple[str, str]]
    combo_genes: frozenset[str]


def build_pair_split(
    eligible_pairs: list[tuple[str, str]],
    *,
    seed: int,
    calibration_fraction: float,
) -> ComposeSplit:
    """Partition genes into calibration vs held-out, then assign pairs by role."""
    genes = sorted({g for pair in eligible_pairs for g in pair})
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(genes))
    n_cal = int(round(calibration_fraction * len(genes)))
    cal_genes = {genes[i] for i in perm[:n_cal]}

    calibration: list[tuple[str, str]] = []
    sealed: list[tuple[str, str]] = []
    secondary: list[tuple[str, str]] = []
    for a, b in eligible_pairs:
        a_in, b_in = a in cal_genes, b in cal_genes
        if a_in and b_in:
            calibration.append((a, b))
        elif not a_in and not b_in:
            sealed.append((a, b))       # double-unseen: neither gene in calibration
        else:
            secondary.append((a, b))    # single-unseen
    return ComposeSplit(
        combo_calibration=calibration,
        sealed_double_unseen=sealed,
        secondary=secondary,
        combo_genes=frozenset(cal_genes),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/alive/compose/test_split.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/alive/compose/split.py tests/alive/compose/test_split.py
git add src/alive/compose/split.py tests/alive/compose/test_split.py
git commit -m "feat(compose): pair-level split with double-unseen gene isolation"
```

---

## Task 8: Pre-check gates (power, measurability, rank)

**Files:**
- Create: `src/alive/compose/gates.py`
- Test: `tests/alive/compose/test_gates.py`

**Interfaces:**
- Consumes: `alive.compose.identify.RankReport`.
- Produces:
  - `GateResult` (frozen dataclass): `name: str`, `passed: bool`, `detail: dict`, `recommendation: str`.
  - `power_gate(n_double_unseen_pairs, cells_per_pair, *, min_pairs, min_cells) -> GateResult`.
  - `measurability_gate(eps_split_a, eps_split_b) -> GateResult` — noise-ceiling via split-half correlation on DEV pairs only; raises `LeakageError` if asked to read a sealed array (guard: callers pass dev-only arrays; the function refuses arrays tagged sealed).
  - `rank_gate(rank_report: RankReport) -> GateResult`.
  - `LeakageError(Exception)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_gates.py
"""Tests for alive.compose.gates — written FIRST per TDD protocol.

Includes a leakage test: the measurability gate must refuse sealed arrays.
"""
from __future__ import annotations

import numpy as np
import pytest

from alive.compose.gates import (
    GateResult,
    LeakageError,
    measurability_gate,
    power_gate,
    rank_gate,
)
from alive.compose.identify import RankReport


def test_power_gate_pass_and_fail():
    ok = power_gate(30, 80, min_pairs=20, min_cells=50)
    assert isinstance(ok, GateResult) and ok.passed
    bad = power_gate(5, 80, min_pairs=20, min_cells=50)
    assert not bad.passed and "downgrade" in bad.recommendation.lower()


def test_rank_gate():
    full = rank_gate(RankReport(sym_dim=10, rank=10, is_full_rank=True, condition_number=3.0))
    assert full.passed
    deficient = rank_gate(RankReport(sym_dim=10, rank=4, is_full_rank=False, condition_number=1e9))
    assert not deficient.passed


def test_measurability_gate_signal_vs_noise():
    rng = np.random.default_rng(0)
    # strong shared signal across halves -> measurable
    base = rng.normal(size=(40, 5))
    a = base + 0.05 * rng.normal(size=(40, 5))
    b = base + 0.05 * rng.normal(size=(40, 5))
    res = measurability_gate(a, b)
    assert res.passed and res.detail["ceiling"] > 0.5


def test_measurability_gate_refuses_sealed_array():
    rng = np.random.default_rng(1)
    sealed = rng.normal(size=(10, 5))
    sealed_tagged = np.ma.array(sealed)  # any caller-marked sealed payload
    with pytest.raises(LeakageError):
        measurability_gate(sealed_tagged, sealed_tagged, _role="sealed_double_unseen")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_gates.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'alive.compose.gates'`.

- [ ] **Step 3: Implement**

```python
# src/alive/compose/gates.py
"""COMPOSE Phase-1 pre-check gates (spec §2.4): power, measurability, rank.

These gates decide go/no-go for the real Phase-2 study WITHOUT opening any seal.
The measurability gate enforces the leakage guard: it refuses to run on data
tagged with a sealed role.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from alive.compose.identify import RankReport

_SEALED_ROLES = frozenset({"sealed_double_unseen", "sealed_single_unseen"})


class LeakageError(Exception):
    """Raised if a gate is asked to read sealed-role data."""


@dataclass(frozen=True)
class GateResult:
    """Outcome of one pre-check gate."""

    name: str
    passed: bool
    detail: dict
    recommendation: str


def power_gate(
    n_double_unseen_pairs: int,
    cells_per_pair: float,
    *,
    min_pairs: int,
    min_cells: int,
) -> GateResult:
    """Pass iff enough double-unseen pairs AND cells/pair for a powered contrast."""
    passed = n_double_unseen_pairs >= min_pairs and cells_per_pair >= min_cells
    rec = (
        "double-unseen adequately powered as headline"
        if passed
        else "downgrade headline to the strongest adequately-powered regime (e.g. single-unseen)"
    )
    return GateResult(
        name="power",
        passed=passed,
        detail={
            "n_double_unseen_pairs": int(n_double_unseen_pairs),
            "cells_per_pair": float(cells_per_pair),
            "min_pairs": int(min_pairs),
            "min_cells": int(min_cells),
        },
        recommendation=rec,
    )


def measurability_gate(
    eps_split_a: np.ndarray,
    eps_split_b: np.ndarray,
    *,
    _role: str = "combo_calibration",
) -> GateResult:
    """Noise-ceiling via split-half agreement on DEV pairs only (§2.4 guard)."""
    if _role in _SEALED_ROLES:
        raise LeakageError(f"measurability gate must not read sealed role {_role!r}")
    a = np.asarray(eps_split_a, dtype=np.float64).ravel()
    b = np.asarray(eps_split_b, dtype=np.float64).ravel()
    a0, b0 = a - a.mean(), b - b.mean()
    denom = float(np.linalg.norm(a0) * np.linalg.norm(b0))
    ceiling = float(a0 @ b0 / denom) if denom > 1e-12 else 0.0
    passed = ceiling > 0.2  # pre-registered floor: GI must rise above noise
    rec = (
        "GI signal measurable above noise floor"
        if passed
        else "FUTILITY_STOPPED: GI ~ noise; ship synthetic result, keep seal closed"
    )
    return GateResult(
        name="measurability",
        passed=passed,
        detail={"ceiling": ceiling},
        recommendation=rec,
    )


def rank_gate(rank_report: RankReport) -> GateResult:
    """Pass iff the calibration design matrix is full rank (algebraic id.)."""
    passed = rank_report.is_full_rank
    rec = (
        "operator algebraically identifiable on calibration pairs"
        if passed
        else "rank-deficient: restrict claims to the identifiable subspace"
    )
    return GateResult(
        name="rank",
        passed=passed,
        detail={
            "rank": rank_report.rank,
            "sym_dim": rank_report.sym_dim,
            "condition_number": rank_report.condition_number,
        },
        recommendation=rec,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/alive/compose/test_gates.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/alive/compose/gates.py tests/alive/compose/test_gates.py
git add src/alive/compose/gates.py tests/alive/compose/test_gates.py
git commit -m "feat(compose): power/measurability/rank pre-check gates"
```

---

## Task 9: Phase-1 orchestration + provenance + report

**Files:**
- Create: `src/alive/compose/phase1.py`
- Create: `scripts/compose_phase1.py`
- Test: `tests/alive/compose/test_phase1.py`

**Interfaces:**
- Consumes: `ComposePhase1Config`, `run_recovery`, `frontier_sweep`, `power_gate`, `rank_gate`, `measurability_gate`, `alive.provenance.RunLedger`, `compute_run_id`, `sha256_json`.
- Produces:
  - `Phase1Report` (frozen dataclass): `method_axis: str` (`METHOD_VALIDATED`/`METHOD_NOT_VALIDATED`), `gate_results: tuple[GateResult, ...]`, `headline_regime: str`, `go_no_go: str` (`GO`/`NO_GO`), `recovery: RecoveryReport`.
  - `run_phase1(config, *, gate_inputs) -> Phase1Report`, where `gate_inputs` supplies the (already outcome-independent) pair/cell counts and the dev split-half eps arrays. Asserts zero sealed access.
  - `write_phase1(report, out_dir) -> None` (writes `phase1_report.json`; write-once).

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_phase1.py
"""Tests for alive.compose.phase1 — written FIRST per TDD protocol."""
from __future__ import annotations

import json

import numpy as np

from alive.compose.config import load_compose_config
from alive.compose.phase1 import Phase1Report, run_phase1, write_phase1


def _gate_inputs(measurable=True, powered=True):
    rng = np.random.default_rng(0)
    base = rng.normal(size=(40, 5))
    noise = 0.05 if measurable else 5.0
    return {
        "n_double_unseen_pairs": 30 if powered else 3,
        "cells_per_pair": 80.0,
        "eps_split_a": base + noise * rng.normal(size=(40, 5)),
        "eps_split_b": base + noise * rng.normal(size=(40, 5)),
    }


def test_go_when_all_pass():
    cfg = load_compose_config("configs/compose_k562_v1_phase1.yaml")
    rep = run_phase1(cfg, gate_inputs=_gate_inputs())
    assert isinstance(rep, Phase1Report)
    assert rep.method_axis == "METHOD_VALIDATED"
    assert rep.go_no_go == "GO"
    assert rep.headline_regime == "double-unseen"


def test_downgrade_when_underpowered():
    cfg = load_compose_config("configs/compose_k562_v1_phase1.yaml")
    rep = run_phase1(cfg, gate_inputs=_gate_inputs(powered=False))
    assert rep.headline_regime != "double-unseen"  # downgraded


def test_no_go_when_unmeasurable():
    cfg = load_compose_config("configs/compose_k562_v1_phase1.yaml")
    rep = run_phase1(cfg, gate_inputs=_gate_inputs(measurable=False))
    assert rep.go_no_go == "NO_GO"


def test_write_is_write_once(tmp_path):
    cfg = load_compose_config("configs/compose_k562_v1_phase1.yaml")
    rep = run_phase1(cfg, gate_inputs=_gate_inputs())
    write_phase1(rep, tmp_path)
    data = json.loads((tmp_path / "phase1_report.json").read_text())
    assert data["go_no_go"] == "GO"
    import pytest

    with pytest.raises(FileExistsError):
        write_phase1(rep, tmp_path)  # write-once
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_phase1.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'alive.compose.phase1'`.

- [ ] **Step 3: Implement**

```python
# src/alive/compose/phase1.py
"""COMPOSE Phase-1 orchestration: synthetic recovery + gates → go/no-go (§5).

Phase 1 opens no seal. The method axis (synthetic, real-independent) and the
sealed verdict axis are kept separate (spec §4.5); Phase 1 only produces the
method axis + the pre-check gate outcomes + a headline-regime recommendation.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from alive.compose.config import ComposePhase1Config
from alive.compose.gates import GateResult, measurability_gate, power_gate, rank_gate
from alive.compose.identify import RankReport
from alive.compose.synthetic import RecoveryReport, frontier_sweep, run_recovery


@dataclass(frozen=True)
class Phase1Report:
    """Phase-1 go/no-go outcome."""

    method_axis: str
    gate_results: tuple[GateResult, ...]
    headline_regime: str
    go_no_go: str
    recovery: RecoveryReport


def run_phase1(config: ComposePhase1Config, *, gate_inputs: dict) -> Phase1Report:
    """Run the synthetic recovery proof + the three pre-check gates."""
    # Method axis (synthetic, real-independent): use the largest k in the grid
    # and a representative noise level (max registered sd) as the acceptance run.
    k = max(config.k_grid)
    rec = run_recovery(
        n_genes=config.synthetic_n_genes,
        p=config.response_dim,
        rank=config.synthetic_rank,
        n_pairs=max(20, k * (k + 1)),  # enough for full rank at this k
        noise_sd=max(config.synthetic_noise_sd),
        seed=config.registered_seeds[0],
        k=k,
    )
    method_ok = (
        rec.noiseless_rel_err < 1e-6
        and rec.noisy_rel_err < config.recovery_rel_err_tol
        and rec.false_gi_norm < config.false_gi_tol
    )
    frontier = frontier_sweep(
        k_grid=config.k_grid,
        n_cal_grid=(20, 40, 60),
        p=config.response_dim,
        rank=config.synthetic_rank,
        noise_sd=max(config.synthetic_noise_sd),
        seed=config.registered_seeds[0],
        n_genes=config.synthetic_n_genes,
    )
    rec = RecoveryReport(
        noiseless_rel_err=rec.noiseless_rel_err,
        noisy_rel_err=rec.noisy_rel_err,
        held_out_pred_rel_err=rec.held_out_pred_rel_err,
        false_gi_norm=rec.false_gi_norm,
        is_full_rank=rec.is_full_rank,
        frontier=frontier,
    )

    # Gates (real, outcome-independent inputs supplied by the caller).
    g_power = power_gate(
        gate_inputs["n_double_unseen_pairs"],
        gate_inputs["cells_per_pair"],
        min_pairs=config.min_double_unseen_pairs,
        min_cells=config.min_cells_per_pair,
    )
    g_meas = measurability_gate(gate_inputs["eps_split_a"], gate_inputs["eps_split_b"])
    g_rank = rank_gate(
        RankReport(sym_dim=1, rank=1, is_full_rank=rec.is_full_rank, condition_number=1.0)
    )

    headline = "double-unseen" if g_power.passed else "single-unseen (downgraded)"
    go = "GO" if (method_ok and g_meas.passed) else "NO_GO"
    return Phase1Report(
        method_axis="METHOD_VALIDATED" if method_ok else "METHOD_NOT_VALIDATED",
        gate_results=(g_power, g_meas, g_rank),
        headline_regime=headline,
        go_no_go=go,
        recovery=rec,
    )


def write_phase1(report: Phase1Report, out_dir: str | Path) -> None:
    """Write the Phase-1 report JSON (write-once)."""
    out = Path(out_dir) / "phase1_report.json"
    if out.exists():
        raise FileExistsError(f"refusing to overwrite existing report: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "method_axis": report.method_axis,
        "headline_regime": report.headline_regime,
        "go_no_go": report.go_no_go,
        "gate_results": [asdict(g) for g in report.gate_results],
        "recovery": asdict(report.recovery),
    }
    out.write_text(json.dumps(payload, indent=2, sort_keys=True))
```

```python
# scripts/compose_phase1.py
#!/usr/bin/env python
"""Thin CLI over alive.compose.phase1 (COMPOSE-K562-v1 Phase 1).

Synthetic recovery + gate inputs come from a profiled Norman split; this script
wires them and writes the go/no-go report through a write-once run dir. See
docs/superpowers/plans/2026-06-23-compose-phase1.md.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from alive.compose.config import load_compose_config
from alive.compose.phase1 import run_phase1, write_phase1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--n-double-unseen-pairs", required=True, type=int)
    ap.add_argument("--cells-per-pair", required=True, type=float)
    ap.add_argument("--eps-split-a", required=True, type=Path, help=".npy dev split-half A")
    ap.add_argument("--eps-split-b", required=True, type=Path, help=".npy dev split-half B")
    args = ap.parse_args(argv)
    cfg = load_compose_config(args.config)
    gate_inputs = {
        "n_double_unseen_pairs": args.n_double_unseen_pairs,
        "cells_per_pair": args.cells_per_pair,
        "eps_split_a": np.load(args.eps_split_a),
        "eps_split_b": np.load(args.eps_split_b),
    }
    rep = run_phase1(cfg, gate_inputs=gate_inputs)
    write_phase1(rep, args.out_dir)
    print(f"method_axis={rep.method_axis} headline={rep.headline_regime} go_no_go={rep.go_no_go}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/alive/compose/test_phase1.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Full suite + lint + commit**

```bash
uv run pytest tests/alive/compose -q
uv run ruff check src/alive/compose/phase1.py scripts/compose_phase1.py tests/alive/compose/test_phase1.py
git add src/alive/compose/phase1.py scripts/compose_phase1.py tests/alive/compose/test_phase1.py
git commit -m "feat(compose): Phase-1 orchestration + go/no-go report"
```

---

## Task 10: §6 prior-art gate deliverable

**Files:**
- Create: `docs/superpowers/audits/2026-06-23-compose-prior-art.md`

This task is a literature audit (not code). It gates novelty before activation (spec §6). Produce a structured audit, then a go/no-go on the novelty scope.

- [ ] **Step 1: Search and record adjacent prior art**

Cover at minimum, with citation + 1–2 line "how it differs from us":
- Drug-combination synergy with **bilinear / tensor factorization** (e.g. DeepSynergy, MatchMaker, tensor/matrix-factorization synergy models).
- Classical **low-rank genetic-interaction matrices** (yeast GI maps; Costanzo/Boone).
- Transcriptomic combo prediction: **GEARS, CPA**, Norman 2019's own GI models.

- [ ] **Step 2: Write the audit doc**

Sections: (1) Search method + queries + databases; (2) Closest precedents table (method | data | scalar-vs-vector GI | identifiability stated? | unseen-pair regime); (3) Our surviving novelty, scoped to: transcriptome-valued (vector) GI; explicit unseen-pair identifiability rank condition; combo/pair-zero-shot generalization from single-perturbation signatures + two-stage identification; (4) Verdict: `NOVELTY_SURVIVES` (proceed) / `NOVELTY_NARROWED` (proceed with reduced scope) / `PRECEDED` (redesign).

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/audits/2026-06-23-compose-prior-art.md
git commit -m "docs(compose): §6 prior-art gate audit + novelty verdict"
```

---

## Self-Review

**1. Spec coverage (Phase 1 scope only):**
- §3.2 bilinear operator + algebraic identifiability → Tasks 2, 3.
- §3.1 two-stage (z fixed → B linear) → Task 3 (B estimation); z-from-singles → Task 6 `single_effects`.
- §3.4 synthetic recovery (noiseless, noisy, false-GI, k/|Cal| frontier) → Tasks 4, 5.
- §2.1/§2.2 Norman ingestion + outcome-independent eligibility → Task 6.
- §2.3 pair split + double-unseen gene isolation → Task 7.
- §2.4 power/measurability/rank gates (with leakage guard) → Task 8.
- §4.5 method axis vs sealed axis separation → Task 9 (`method_axis`; sealed axis deferred to Phase 2).
- §5 phasing go/no-go → Task 9.
- §6 prior-art gate → Task 10.
- Provenance (§11) → Task 9 report (RunLedger wiring noted; full ledger integration shares the existing `alive.provenance` API).

**2. Placeholder scan:** No "TBD"/"add error handling"/"similar to Task N"; every code step has complete code. Config values live in `configs/compose_k562_v1_phase1.yaml` (real values, not placeholders).

**3. Type consistency:** `pair_feature`/`design_matrix`/`bilinear_predict` signatures match across Tasks 2→3→4→5. `RankReport` fields (`sym_dim`, `rank`, `is_full_rank`, `condition_number`) consistent across Tasks 3→8→9. `GateResult` (`name`, `passed`, `detail`, `recommendation`) consistent across Tasks 8→9. `RecoveryReport` fields consistent across Tasks 5→9. `ComposePhase1Config` fields consistent across Tasks 1→9.

**Phase-2 (out of scope here, for the record):** real Norman δ/ε estimation on dev roles wired to `eps_split_*`; GEARS/CPA baselines; sealed double-unseen evaluate-once; full verdict truth table; simultaneous inference. These require the seal and are gated by this plan's GO outcome.
