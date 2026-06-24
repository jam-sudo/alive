# COMPOSE-K562-v1 Phase 2b (seal + verdict) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the COMPOSE Phase-2b sealed-evaluation machinery — an independent write-once COMPOSE outcome store, max-deviation bootstrap simultaneous inference over the comparator family, the two-axis verdict, and the seal-once orchestrator with provenance — all validated on SYNTHETIC fixtures, opening NO real seal.

**Architecture:** A `ComposeOutcomeStore` (separate namespace `artifacts/compose/<run_id>`, write-once, audited, double-open-refusing) releases sealed-pair outcomes exactly once. `inference2` computes simultaneous 95% lower bounds for each contrast (L1 vs additive/GEARS/CPA/ID-only/L3) via a shared-resample max-deviation bootstrap on per-pair errors. `verdict2` maps those bounds to {GI_LEARNABLE_WIN/PARTIAL/NO_DISTINCT_WIN/INVALID} (sealed axis) alongside the synthetic METHOD axis. `phase2b` freezes all methods, opens the seal once, scores, infers, decides, and writes a write-once report + composite-run-id provenance.

**Tech Stack:** Python 3.11–3.12, numpy; ruff (line length 100); pytest. Reuses `alive.compose.{metric2,phase2a}`, `alive.provenance`.

## Global Constraints

- **Contract:** spec `…/2026-06-22-compose-epistasis-operator-design.md` §10.5–§10.6 + `configs/compose_k562_v1_phase2.yaml`. Status PRE-REGISTERED, ACTIVATION BLOCKED.
- **Builds + tests on SYNTHETIC fixtures only.** No real Norman sealed pairs are read; the actual seal-once on real data happens only after the owner activation commit.
- **Seal-once:** sealed access count 0 → exactly 1; a second open is refused (write-once state machine). Independent of TG-K562 (§6.3).
- **Predictions are FROZEN before the seal opens.** Phase-2b scores pre-computed frozen predictions against released outcomes; it never fits.
- **Simultaneous inference:** shared resamples across all contrasts, 10000 replicates, family-confidence 0.95; verdict thresholds verbatim from config.
- **No overclaiming:** report structural clauses with the "self-check, not an independent audit" disclaimer; futility ≠ verdict; report both axes + all regimes (double-unseen headline, single-unseen secondary).
- Production logic in `src/alive/`, tests under `tests/alive/compose/`; NumPy-style docstrings + type hints; ruff line length 100; `uv run`. Commits end with the repo trailers.

---

## File Structure

| Path | Responsibility |
|---|---|
| `src/alive/compose/outcome_store.py` | Independent write-once COMPOSE seal store + access audit (0→1, double-open refused). |
| `src/alive/compose/inference2.py` | Shared-resample max-deviation bootstrap → simultaneous lower bounds per contrast. |
| `src/alive/compose/verdict2.py` | Config-threshold verdict (sealed axis) + method axis. |
| `src/alive/compose/phase2b.py` | Freeze → seal-once → score frozen preds → inference → verdict → write-once report + provenance. |
| `tests/alive/compose/` | unit / known-answer / seal-once integration / tamper tests. |

---

## Task 1: Independent write-once COMPOSE outcome store

**Files:**
- Create: `src/alive/compose/outcome_store.py`
- Test: `tests/alive/compose/test_outcome_store.py`

**Interfaces:**
- Consumes: `alive.provenance.sha256_json`.
- Produces:
  - `SealError(RuntimeError)`.
  - `ComposeOutcomeStore(run_dir)` with `seal(outcomes: dict[str, np.ndarray]) -> None` (write-once persist of sealed-pair outcomes + audit init), `open_once() -> dict[str, np.ndarray]` (increments audit 0→1; second call raises `SealError`), `access_count() -> int`.

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_outcome_store.py
"""Tests for alive.compose.outcome_store — written FIRST per TDD protocol."""
from __future__ import annotations

import numpy as np
import pytest

from alive.compose.outcome_store import ComposeOutcomeStore, SealError


def test_seal_then_open_once(tmp_path):
    store = ComposeOutcomeStore(tmp_path / "run")
    store.seal({"A_B": np.array([1.0, 2.0])})
    assert store.access_count() == 0
    got = store.open_once()
    np.testing.assert_allclose(got["A_B"], [1.0, 2.0])
    assert store.access_count() == 1


def test_second_open_refused(tmp_path):
    store = ComposeOutcomeStore(tmp_path / "run")
    store.seal({"A_B": np.array([1.0])})
    store.open_once()
    with pytest.raises(SealError):
        store.open_once()


def test_reseal_refused(tmp_path):
    store = ComposeOutcomeStore(tmp_path / "run")
    store.seal({"A_B": np.array([1.0])})
    with pytest.raises(SealError):
        store.seal({"A_B": np.array([2.0])})  # write-once
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/alive/compose/test_outcome_store.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/alive/compose/outcome_store.py
"""Independent, write-once COMPOSE sealed-outcome store (§6.3, §10.6).

Separate namespace from TG-K562. Outcomes are persisted once; opened exactly
once; a second open or a re-seal raises. The audit file records the access count.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


class SealError(RuntimeError):
    """Raised on write-once / seal-once violations."""


class ComposeOutcomeStore:
    """Write-once sealed outcomes + access audit under ``run_dir``."""

    def __init__(self, run_dir: str | Path):
        self.run_dir = Path(run_dir)
        self._npz = self.run_dir / "sealed_outcomes.npz"
        self._audit = self.run_dir / "seal_audit.json"

    def seal(self, outcomes: dict[str, np.ndarray]) -> None:
        if self._npz.exists():
            raise SealError(f"already sealed: {self._npz}")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        np.savez(self._npz, **outcomes)
        self._audit.write_text(json.dumps({"access_count": 0}))

    def access_count(self) -> int:
        if not self._audit.exists():
            return 0
        return int(json.loads(self._audit.read_text())["access_count"])

    def open_once(self) -> dict[str, np.ndarray]:
        if not self._npz.exists():
            raise SealError("nothing sealed")
        if self.access_count() >= 1:
            raise SealError("seal already opened exactly once")
        self._audit.write_text(json.dumps({"access_count": 1}))
        npz = np.load(self._npz, allow_pickle=False)
        return {k: npz[k] for k in npz.files}
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/alive/compose/test_outcome_store.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/alive/compose/outcome_store.py tests/alive/compose/test_outcome_store.py
git add src/alive/compose/outcome_store.py tests/alive/compose/test_outcome_store.py
git commit -m "feat(compose): independent write-once seal-once outcome store"
```

---

## Task 2: Shared-resample max-deviation bootstrap simultaneous lower bounds

**Files:**
- Create: `src/alive/compose/inference2.py`
- Test: `tests/alive/compose/test_inference2.py`

**Interfaces:**
- Consumes: numpy.
- Produces:
  - `simultaneous_lower_bounds(e_model, e_by_comparator, *, replicates, confidence, seed) -> dict[str, float]` — for each comparator C, the relative improvement `θ_C = 1 - mean(e_model)/max(mean(e_C),1e-12)`; resample PAIRS once per replicate (shared across contrasts), recompute every `θ_C`, and return the family-wise simultaneous lower bound for each C (so that all bounds hold jointly at `confidence`).

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_inference2.py
"""Tests for alive.compose.inference2 — written FIRST per TDD protocol."""
from __future__ import annotations

import numpy as np

from alive.compose.inference2 import simultaneous_lower_bounds


def test_strong_improvement_has_positive_bounds():
    rng = np.random.default_rng(0)
    n = 200
    e_model = np.abs(rng.normal(0.1, 0.02, n))      # small errors
    e_cmp = {"additive": np.abs(rng.normal(1.0, 0.1, n))}  # large errors
    lb = simultaneous_lower_bounds(e_model, e_cmp, replicates=2000, confidence=0.95, seed=1)
    assert lb["additive"] > 0.5                      # clearly improved


def test_no_improvement_bound_not_positive():
    rng = np.random.default_rng(0)
    n = 200
    e = np.abs(rng.normal(1.0, 0.1, n))
    lb = simultaneous_lower_bounds(e, {"additive": e.copy()}, replicates=2000, confidence=0.95, seed=1)
    assert lb["additive"] <= 0.05                    # equal errors -> no material win


def test_bounds_present_for_every_comparator():
    rng = np.random.default_rng(2)
    n = 100
    e_model = np.abs(rng.normal(0.2, 0.05, n))
    e_cmp = {c: np.abs(rng.normal(0.5, 0.1, n)) for c in ("additive", "gears", "cpa")}
    lb = simultaneous_lower_bounds(e_model, e_cmp, replicates=1000, confidence=0.95, seed=3)
    assert set(lb) == {"additive", "gears", "cpa"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/alive/compose/test_inference2.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/alive/compose/inference2.py
"""Shared-resample max-deviation bootstrap for simultaneous lower bounds (§10.5).

Each replicate resamples PAIRS once and recomputes every contrast's relative
improvement, so the family-wise bounds hold jointly. The simultaneous lower
bound per comparator is theta_hat minus the (1-confidence) max-deviation
quantile of (theta_hat - theta_boot) across the family.
"""
from __future__ import annotations

import numpy as np


def _theta(e_model: np.ndarray, e_cmp: np.ndarray) -> float:
    return 1.0 - float(np.mean(e_model)) / max(float(np.mean(e_cmp)), 1e-12)


def simultaneous_lower_bounds(
    e_model: np.ndarray,
    e_by_comparator: dict[str, np.ndarray],
    *,
    replicates: int,
    confidence: float,
    seed: int,
) -> dict[str, float]:
    """Family-wise simultaneous lower bounds for each relative-improvement contrast."""
    e_model = np.asarray(e_model, dtype=np.float64)
    names = list(e_by_comparator)
    E = {c: np.asarray(e_by_comparator[c], dtype=np.float64) for c in names}
    n = len(e_model)
    point = {c: _theta(e_model, E[c]) for c in names}

    rng = np.random.Generator(np.random.PCG64(seed))
    max_dev = np.zeros(replicates)
    boot = {c: np.empty(replicates) for c in names}
    for r in range(replicates):
        idx = rng.integers(0, n, n)              # shared resample across contrasts
        em = e_model[idx]
        devs = []
        for c in names:
            tb = _theta(em, E[c][idx])
            boot[c][r] = tb
            devs.append(point[c] - tb)
        max_dev[r] = max(devs)
    q = float(np.quantile(max_dev, confidence))  # joint margin
    return {c: point[c] - q for c in names}
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/alive/compose/test_inference2.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/alive/compose/inference2.py tests/alive/compose/test_inference2.py
git add src/alive/compose/inference2.py tests/alive/compose/test_inference2.py
git commit -m "feat(compose): shared-resample max-deviation simultaneous lower bounds"
```

---

## Task 3: Verdict mapping (sealed axis + method axis)

**Files:**
- Create: `src/alive/compose/verdict2.py`
- Test: `tests/alive/compose/test_verdict2.py`

**Interfaces:**
- Produces:
  - `sealed_verdict(lower_bounds, *, additive_margin, learned_margin, integrity_ok) -> str` → `INVALID` if not `integrity_ok`; else `GI_LEARNABLE_WIN` if `lb["additive"] > additive_margin` and every learned `lb[c] > learned_margin`; `PARTIAL` if `lb["additive"] > additive_margin` but a learned fails; `NO_DISTINCT_WIN` if `lb["additive"] <= additive_margin`.
  - `combined_verdict(method_validated, sealed) -> dict` → `{"method_axis", "sealed_axis"}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_verdict2.py
"""Known-answer tests for alive.compose.verdict2 (config thresholds)."""
from __future__ import annotations

from alive.compose.verdict2 import combined_verdict, sealed_verdict

LEARNED = ["gears", "cpa", "id_only", "l3_hypernetwork"]


def _lb(additive, learned):
    d = {"additive": additive}
    d.update({c: learned for c in LEARNED})
    return d


def test_gi_learnable_win():
    v = sealed_verdict(_lb(0.10, 0.02), additive_margin=0.05, learned_margin=0.0, integrity_ok=True)
    assert v == "GI_LEARNABLE_WIN"


def test_partial_when_learned_fails():
    lb = _lb(0.10, 0.02); lb["gears"] = -0.1
    v = sealed_verdict(lb, additive_margin=0.05, learned_margin=0.0, integrity_ok=True)
    assert v == "PARTIAL"


def test_no_distinct_win_when_additive_not_cleared():
    v = sealed_verdict(_lb(0.01, 0.5), additive_margin=0.05, learned_margin=0.0, integrity_ok=True)
    assert v == "NO_DISTINCT_WIN"


def test_invalid_overrides():
    v = sealed_verdict(_lb(0.9, 0.9), additive_margin=0.05, learned_margin=0.0, integrity_ok=False)
    assert v == "INVALID"


def test_combined_axes():
    out = combined_verdict(method_validated=True, sealed="NO_DISTINCT_WIN")
    assert out == {"method_axis": "METHOD_VALIDATED", "sealed_axis": "NO_DISTINCT_WIN"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/alive/compose/test_verdict2.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/alive/compose/verdict2.py
"""COMPOSE Phase-2 verdict mapping (spec §10.5 / config thresholds).

Two axes: method (synthetic) and sealed (real). Sealed verdict requires the
additive simultaneous lower bound > additive_margin AND every learned comparator
lower bound > learned_margin for a GI_LEARNABLE_WIN.
"""
from __future__ import annotations


def sealed_verdict(
    lower_bounds: dict[str, float],
    *,
    additive_margin: float,
    learned_margin: float,
    integrity_ok: bool,
) -> str:
    """Map simultaneous lower bounds to the sealed-axis verdict."""
    if not integrity_ok:
        return "INVALID"
    learned = [c for c in lower_bounds if c != "additive"]
    additive_ok = lower_bounds["additive"] > additive_margin
    learned_ok = all(lower_bounds[c] > learned_margin for c in learned)
    if additive_ok and learned_ok:
        return "GI_LEARNABLE_WIN"
    if additive_ok:
        return "PARTIAL"
    return "NO_DISTINCT_WIN"


def combined_verdict(method_validated: bool, sealed: str) -> dict[str, str]:
    """Combine the synthetic method axis with the sealed axis."""
    return {
        "method_axis": "METHOD_VALIDATED" if method_validated else "METHOD_NOT_VALIDATED",
        "sealed_axis": sealed,
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/alive/compose/test_verdict2.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/alive/compose/verdict2.py tests/alive/compose/test_verdict2.py
git add src/alive/compose/verdict2.py tests/alive/compose/test_verdict2.py
git commit -m "feat(compose): Phase-2 verdict mapping (sealed + method axes)"
```

---

## Task 4: Phase-2b orchestrator + seal-once integration test

**Files:**
- Create: `src/alive/compose/phase2b.py`
- Test: `tests/alive/compose/test_phase2b.py`

**Interfaces:**
- Consumes: `ComposeOutcomeStore`, `alive.compose.metric2.pair_errors`, `simultaneous_lower_bounds`, `sealed_verdict`/`combined_verdict`, `alive.provenance.{sha256_json,sha256_file}`.
- Produces:
  - `run_phase2b(run_dir, frozen_preds, sealed_truth, *, method_validated, additive_margin, learned_margin, replicates, confidence, seed, config_path) -> dict` — seals `sealed_truth` (if not sealed), opens ONCE, computes per-method pair errors vs released truth, simultaneous lower bounds for each contrast L1-vs-comparator, verdict (two axes), writes write-once `phase2b_report.json` + `phase2b_provenance.json`. `frozen_preds` maps method → (n_pairs, p) array; `sealed_truth` maps pair-id → (p,) truth. Integrity_ok = all methods present + all-finite.

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_phase2b.py
"""Tests for alive.compose.phase2b — written FIRST per TDD protocol (incl. seal-once)."""
from __future__ import annotations

import json

import numpy as np
import pytest

from alive.compose.outcome_store import SealError
from alive.compose.phase2b import run_phase2b


def _frozen(seed=0, n=40, p=5):
    rng = np.random.default_rng(seed)
    truth_mat = rng.normal(size=(n, p))
    ids = [f"G{i}_H{i}" for i in range(n)]
    sealed_truth = {ids[i]: truth_mat[i] for i in range(n)}
    preds = {
        "l1_bilinear_identifiable": {ids[i]: truth_mat[i] + 0.05 * rng.normal(size=p) for i in range(n)},
        "additive": {ids[i]: truth_mat[i] + 0.6 * rng.normal(size=p) for i in range(n)},
        "gears": {ids[i]: truth_mat[i] + 0.5 * rng.normal(size=p) for i in range(n)},
        "cpa": {ids[i]: truth_mat[i] + 0.55 * rng.normal(size=p) for i in range(n)},
        "id_only": {ids[i]: truth_mat[i] + 0.5 * rng.normal(size=p) for i in range(n)},
        "l3_hypernetwork": {ids[i]: truth_mat[i] + 0.4 * rng.normal(size=p) for i in range(n)},
    }
    return preds, sealed_truth


def test_run_phase2b_produces_verdict_and_seals_once(tmp_path, monkeypatch):
    preds, truth = _frozen()
    cfg = tmp_path / "cfg.yaml"; cfg.write_text("protocol: COMPOSE-K562-v1\n")
    out = run_phase2b(
        tmp_path / "run", preds, truth, method_validated=True,
        additive_margin=0.05, learned_margin=0.0, replicates=1000, confidence=0.95,
        seed=1, config_path=cfg,
    )
    assert out["combined"]["method_axis"] == "METHOD_VALIDATED"
    assert out["combined"]["sealed_axis"] in (
        "GI_LEARNABLE_WIN", "PARTIAL", "NO_DISTINCT_WIN", "INVALID")
    data = json.loads((tmp_path / "run" / "phase2b_report.json").read_text())
    assert data["sealed_access_count"] == 1


def test_run_phase2b_refuses_second_seal_open(tmp_path):
    preds, truth = _frozen()
    cfg = tmp_path / "cfg.yaml"; cfg.write_text("x: 1\n")
    run_phase2b(tmp_path / "run", preds, truth, method_validated=True,
                additive_margin=0.05, learned_margin=0.0, replicates=200, confidence=0.95,
                seed=1, config_path=cfg)
    with pytest.raises(SealError):
        run_phase2b(tmp_path / "run", preds, truth, method_validated=True,
                    additive_margin=0.05, learned_margin=0.0, replicates=200, confidence=0.95,
                    seed=1, config_path=cfg)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/alive/compose/test_phase2b.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/alive/compose/phase2b.py
"""COMPOSE Phase-2b: freeze -> seal-once -> score -> simultaneous inference ->
verdict -> write-once report + provenance (§10.6).

Phase 2b never fits: it scores FROZEN predictions against outcomes released
exactly once by the independent ComposeOutcomeStore. L1 is the headline method;
contrasts are L1-vs-{additive, gears, cpa, id_only, l3_hypernetwork}.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from alive.compose.inference2 import simultaneous_lower_bounds
from alive.compose.metric2 import pair_errors
from alive.compose.outcome_store import ComposeOutcomeStore
from alive.compose.verdict2 import combined_verdict, sealed_verdict
from alive.provenance import sha256_file, sha256_json

_HEADLINE = "l1_bilinear_identifiable"


def _stack(pred_map: dict, ids: list[str]) -> np.ndarray:
    return np.vstack([pred_map[i] for i in ids])


def run_phase2b(
    run_dir,
    frozen_preds: dict[str, dict[str, np.ndarray]],
    sealed_truth: dict[str, np.ndarray],
    *,
    method_validated: bool,
    additive_margin: float,
    learned_margin: float,
    replicates: int,
    confidence: float,
    seed: int,
    config_path,
) -> dict:
    """Seal-once evaluate the frozen predictions and emit the verdict + provenance."""
    run_dir = Path(run_dir)
    store = ComposeOutcomeStore(run_dir)
    if store.access_count() == 0 and not (run_dir / "sealed_outcomes.npz").exists():
        store.seal({k: np.asarray(v) for k, v in sealed_truth.items()})
    truth = store.open_once()                       # 0 -> 1 (raises on a second run)

    ids = sorted(truth)
    truth_mat = np.vstack([truth[i] for i in ids])
    methods = list(frozen_preds)
    integrity_ok = _HEADLINE in methods and all(
        np.all(np.isfinite(_stack(frozen_preds[m], ids))) for m in methods
    )
    e = {m: pair_errors(_stack(frozen_preds[m], ids), truth_mat) for m in methods}
    comparators = {m: e[m] for m in methods if m != _HEADLINE}
    lbs = simultaneous_lower_bounds(
        e[_HEADLINE], comparators, replicates=replicates, confidence=confidence, seed=seed
    )
    sealed = sealed_verdict(
        lbs, additive_margin=additive_margin, learned_margin=learned_margin,
        integrity_ok=integrity_ok,
    )
    combined = combined_verdict(method_validated, sealed)

    report = {
        "combined": combined,
        "simultaneous_lower_bounds": lbs,
        "sealed_access_count": store.access_count(),
        "n_sealed_pairs": len(ids),
        "integrity_disclaimer": "structural run-internal self-check, NOT an independent audit",
    }
    out = run_dir / "phase2b_report.json"
    if out.exists():
        raise FileExistsError(f"refusing to overwrite {out}")
    out.write_text(json.dumps(report, indent=2, sort_keys=True))
    prov = {
        "config_sha256": sha256_file(config_path),
        "report_sha256": sha256_json(report),
        "phase": "compose_k562_v1_phase2b",
    }
    (run_dir / "phase2b_provenance.json").write_text(json.dumps(prov, indent=2, sort_keys=True))
    return report
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/alive/compose/test_phase2b.py -q`
Expected: PASS (2 passed) — including the seal-once integration test (second run refused).

- [ ] **Step 5: Full compose suite + lint + commit**

```bash
uv run pytest tests/alive/compose -q
uv run ruff check src/alive/compose/phase2b.py tests/alive/compose/test_phase2b.py
git add src/alive/compose/phase2b.py tests/alive/compose/test_phase2b.py
git commit -m "feat(compose): Phase-2b seal-once orchestrator + verdict + provenance"
```

---

## Self-Review

**1. Spec coverage (Phase 2b scope):**
- §10.6 independent write-once seal-once store (0→1) → Task 1 (blocker #5 + the seal-once integration test for blocker #6 lands in Task 4).
- §10.5 shared-resample max-deviation simultaneous lower bounds (10000, 0.95) → Task 2.
- §10.5 verdict thresholds (additive LB>0.05 ∧ each learned LB>0; PARTIAL; NO_DISTINCT_WIN; INVALID) + two axes → Task 3.
- §10.6 freeze → seal-once → score frozen preds → inference → verdict → write-once report + composite provenance → Task 4.

**2. Placeholder scan:** No TBD/"similar to Task N"; complete code every step. The real composite run_id (config+data_card+sequence_mapping+raw_sha256) is recorded at activation when the real data-card exists; Task 4 records config+report SHAs now and the full set is wired from the Phase-2a data-card at activation (blocker #3) — a sequencing note, not a placeholder.

**3. Type consistency:** `ComposeOutcomeStore.open_once()` → dict[str,ndarray] consumed by `run_phase2b`. `pair_errors` (Phase-2a Task 4) reused. `simultaneous_lower_bounds` output keys = comparator names consumed by `sealed_verdict`. `combined_verdict` shape matches the verdict test. `_HEADLINE = "l1_bilinear_identifiable"` matches the config `ablation_ladder` name.

**Activation note:** running 2b on real frozen predictions + real sealed Norman outcomes requires the activation commit (registry → ACTIVE) and all §10.1 blockers; this plan only builds + fixture-tests the machinery (blocker #6).
