# COMPOSE Deep-Baseline Subprocess Backend (Change A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the concrete `SubprocessBaselineBackend` behind the existing `BaselineAdapter` seam so GEARS/CPA can run as separate locked-env subprocesses, with a fully local stub worker; the real gears/cpa workers stay pod-only.

**Architecture:** A new `src/alive/compose/baseline_subprocess.py` adds (1) a versioned payload/prediction serialization protocol with checksums and (2) `SubprocessBaselineBackend` implementing the seam's `is_available`/`predict` contract by serializing a **fit-role-only** payload, invoking a worker script under a locked-env python, and returning response-space δ. A `scripts/baselines/stub_worker.py` provides a deterministic additive-δ backend honoring the protocol, so leakage/protocol/orchestration are 100% locally testable. Fail-closed is enforced upstream: an unavailable backend raises `BaselineUnavailable`, which surfaces as a `FreezeError` at Phase-2a roster assembly.

**Tech Stack:** Python 3.11–3.12, `uv`, `pytest`, `ruff` (line-length 100), `numpy`, stdlib `subprocess`/`json`/`hashlib`. NO new dependency in the main `.venv` (gears/cpa are imported only inside pod-only worker scripts, never by this code).

**Design source:** `docs/superpowers/specs/2026-07-01-compose-deep-baselines-design.md` §1 (spec-review PASSED). Seam: `src/alive/compose/baselines_combo.py`. Roster fail-closed: `src/alive/compose/freeze.py`.

## Global Constraints

- Training roles are **exactly** `{"singles", "combo_calibration"}` (`ALLOWED_ADAPTER_ROLES`). `control` is payload **reference** data (response-space projection + δ reference), and is **never** placed in `context.allowed_roles`.
- The serialized payload MUST contain **no** sealed role / sealed token / sealed path. Reuse the recursive scanner `_assert_no_sealed_reference` from `baselines_combo.py`; `SEALED_TOKENS = ("sealed_double_unseen", "sealed_single_unseen", "sealed")`.
- The backend returns one length-`response_dim` δ vector per requested canonical pair, in the **frozen response space** (the PCA projection is passed to the worker; the worker projects). `_validate_backend_output` in the seam does the final exact check.
- `is_available` MUST be fail-closed: any probe failure ⇒ `False` ⇒ the adapter raises `BaselineUnavailable`. There is no silent mock substitution.
- Real `gears`/`cpa` imports and fits are **out of scope** (pod-only). This plan ships only the stub worker and the protocol/backend around it.
- Determinism: identical `seed` + identical payload ⇒ identical stub predictions.
- ruff clean (line-length 100, `select = E,F,W,I`); NumPy-style docstrings + type hints on public API.

---

## File Structure

- Create `src/alive/compose/baseline_subprocess.py` — payload/prediction serialization (`write_payload`/`read_payload`/`write_predictions`/`read_predictions`, `PayloadError`) + `SubprocessBaselineBackend`.
- Create `scripts/baselines/stub_worker.py` — deterministic additive-δ worker (runs in any python; the protocol reference implementation).
- Create `tests/alive/compose/test_baseline_subprocess.py` — protocol round-trip, is_available, predict-via-stub end-to-end, leakage, determinism.
- Create `tests/alive/compose/test_baseline_failclosed.py` — unavailable backend ⇒ `BaselineUnavailable` ⇒ `FreezeError` at roster assembly.

Each task ends with an independently testable deliverable and a commit.

---

### Task 1: Payload / prediction serialization protocol

**Files:**
- Create: `src/alive/compose/baseline_subprocess.py`
- Test: `tests/alive/compose/test_baseline_subprocess.py`

**Interfaces:**
- Produces: `PayloadError(Exception)`; `write_payload(work_dir: str, payload: dict) -> str` (returns sha256 hex of the canonical payload); `read_payload(work_dir: str) -> dict`; `write_predictions(path: str, preds: dict[tuple[str, str], np.ndarray]) -> str`; `read_predictions(path: str) -> dict[tuple[str, str], np.ndarray]`.
- Payload required keys (exact set; unknown or missing ⇒ `PayloadError`): `schema_version:int`, `response_dim:int`, `seed:int`, `allowed_roles:list[str]`, `pair_ids:list[list[str]]` (canonical `[min,max]`), `single_gene_ids:list[str]`, `singles_response:list[list[float]]`, `control_mean:list[float]`, `calibration_pair_ids:list[list[str]]`, `calibration_delta:list[list[float]]`, `pca_components:list[list[float]]`, `oof_folds:list[int]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/alive/compose/test_baseline_subprocess.py
"""SYNTHETIC-ONLY: pure numpy + subprocess protocol; no gears/cpa, no seal access."""
from __future__ import annotations

import numpy as np
import pytest

from alive.compose.baseline_subprocess import (
    PayloadError,
    read_payload,
    read_predictions,
    write_payload,
    write_predictions,
)


def _payload() -> dict:
    return {
        "schema_version": 1,
        "response_dim": 3,
        "seed": 11,
        "allowed_roles": ["combo_calibration", "singles"],
        "pair_ids": [["A", "B"], ["A", "C"]],
        "single_gene_ids": ["A", "B", "C"],
        "singles_response": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.7, 0.8, 0.9]],
        "control_mean": [0.0, 0.0, 0.0],
        "calibration_pair_ids": [["B", "C"]],
        "calibration_delta": [[0.5, 0.5, 0.5]],
        "pca_components": [[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]],
        "oof_folds": [0],
    }


def test_payload_round_trip_preserves_values_and_checksum(tmp_path):
    p = _payload()
    c1 = write_payload(str(tmp_path), p)
    back = read_payload(str(tmp_path))
    assert back["pair_ids"] == p["pair_ids"]
    assert back["response_dim"] == 3
    np.testing.assert_allclose(back["singles_response"], p["singles_response"])
    # checksum is stable across a re-serialization of the same content
    c2 = write_payload(str(tmp_path), read_payload(str(tmp_path)))
    assert c1 == c2 and len(c1) == 64


def test_missing_key_rejected(tmp_path):
    p = _payload()
    del p["control_mean"]
    with pytest.raises(PayloadError):
        write_payload(str(tmp_path), p)


def test_unknown_key_rejected(tmp_path):
    p = _payload()
    p["surprise"] = 1
    with pytest.raises(PayloadError):
        write_payload(str(tmp_path), p)


def test_prediction_round_trip(tmp_path):
    preds = {("A", "B"): np.array([1.0, 2.0, 3.0]), ("A", "C"): np.array([4.0, 5.0, 6.0])}
    path = str(tmp_path / "preds")
    c = write_predictions(path, preds)
    back = read_predictions(path)
    assert set(back) == set(preds)
    np.testing.assert_allclose(back[("A", "B")], preds[("A", "B")])
    assert len(c) == 64
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/alive/compose/test_baseline_subprocess.py -q`
Expected: FAIL (module `alive.compose.baseline_subprocess` not found).

- [ ] **Step 3: Write minimal implementation**

```python
# src/alive/compose/baseline_subprocess.py
"""SYNTHETIC-ONLY: fit-role-only subprocess protocol for deep combo baselines.

No ``gears``/``cpa`` import here; the real backends run only inside pod-only
worker scripts. This module serializes a fit-role payload, invokes a worker
under a locked-env python, and returns response-space delta. See
docs/superpowers/specs/2026-07-01-compose-deep-baselines-design.md §1.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping

import numpy as np

_SCHEMA_VERSION = 1
_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "schema_version", "response_dim", "seed", "allowed_roles", "pair_ids",
        "single_gene_ids", "singles_response", "control_mean",
        "calibration_pair_ids", "calibration_delta", "pca_components", "oof_folds",
    }
)


class PayloadError(ValueError):
    """Raised on a malformed payload / prediction file (unknown or missing key)."""


def _canonical_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_payload(work_dir: str, payload: dict) -> str:
    keys = set(payload)
    if keys != set(_REQUIRED_KEYS):
        raise PayloadError(f"payload keys {sorted(keys)} != required {sorted(_REQUIRED_KEYS)}")
    if payload["schema_version"] != _SCHEMA_VERSION:
        raise PayloadError(f"unsupported schema_version {payload['schema_version']}")
    os.makedirs(work_dir, exist_ok=True)
    text = _canonical_json(payload)
    with open(os.path.join(work_dir, "payload.json"), "w", encoding="utf-8") as fh:
        fh.write(text)
    return _sha256(text)


def read_payload(work_dir: str) -> dict:
    with open(os.path.join(work_dir, "payload.json"), encoding="utf-8") as fh:
        payload = json.load(fh)
    if set(payload) != set(_REQUIRED_KEYS):
        raise PayloadError("payload on disk has an unexpected key set")
    return payload


def write_predictions(path: str, preds: Mapping[tuple[str, str], np.ndarray]) -> str:
    obj = {"schema_version": _SCHEMA_VERSION,
           "pairs": [[list(p), np.asarray(v, dtype=float).tolist()] for p, v in preds.items()]}
    text = _canonical_json(obj)
    with open(path + ".json", "w", encoding="utf-8") as fh:
        fh.write(text)
    return _sha256(text)


def read_predictions(path: str) -> dict[tuple[str, str], np.ndarray]:
    with open(path + ".json", encoding="utf-8") as fh:
        obj = json.load(fh)
    if obj.get("schema_version") != _SCHEMA_VERSION:
        raise PayloadError("prediction file has an unexpected schema_version")
    return {tuple(pair): np.asarray(vec, dtype=float) for pair, vec in obj["pairs"]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/alive/compose/test_baseline_subprocess.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/baseline_subprocess.py tests/alive/compose/test_baseline_subprocess.py
git commit -m "feat(compose): fit-role subprocess payload/prediction protocol (Change A t1)"
```

---

### Task 2: `SubprocessBaselineBackend.is_available` (fail-closed env probe)

**Files:**
- Modify: `src/alive/compose/baseline_subprocess.py`
- Test: `tests/alive/compose/test_baseline_subprocess.py`

**Interfaces:**
- Produces: `SubprocessBaselineBackend(name: str, env_python: str, worker_script: str, import_name: str)`; property `is_available: bool` — runs `<env_python> -c "import <import_name>"` once (cached), returns `True` only on exit code 0; any exception ⇒ `False`.
- Consumes: nothing from earlier tasks yet.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/alive/compose/test_baseline_subprocess.py
import sys

from alive.compose.baseline_subprocess import SubprocessBaselineBackend


def test_is_available_true_for_importable_module():
    be = SubprocessBaselineBackend(
        name="stub", env_python=sys.executable, worker_script="x", import_name="json"
    )
    assert be.is_available is True


def test_is_available_false_for_missing_module():
    be = SubprocessBaselineBackend(
        name="gears", env_python=sys.executable, worker_script="x",
        import_name="definitely_not_a_real_module_xyz",
    )
    assert be.is_available is False


def test_is_available_false_for_bad_python():
    be = SubprocessBaselineBackend(
        name="cpa", env_python="/no/such/python", worker_script="x", import_name="cpa"
    )
    assert be.is_available is False
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/alive/compose/test_baseline_subprocess.py -k is_available -q`
Expected: FAIL (`SubprocessBaselineBackend` not defined).

- [ ] **Step 3: Implement**

```python
# add to src/alive/compose/baseline_subprocess.py
import subprocess
from dataclasses import dataclass, field


@dataclass
class SubprocessBaselineBackend:
    """Guarded deep-baseline backend that runs a worker under a locked-env python.

    Implements the seam contract (``is_available`` + ``predict``) from
    ``baselines_combo.BaselineAdapter``. Imports no gears/cpa itself.
    """

    name: str
    env_python: str
    worker_script: str
    import_name: str
    seed: int = 11
    _available: bool | None = field(default=None, init=False, repr=False)

    @property
    def is_available(self) -> bool:
        if self._available is None:
            try:
                r = subprocess.run(
                    [self.env_python, "-c", f"import {self.import_name}"],
                    capture_output=True, timeout=120,
                )
                self._available = r.returncode == 0
            except Exception:
                self._available = False
        return self._available
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/alive/compose/test_baseline_subprocess.py -k is_available -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add -u && git commit -m "feat(compose): SubprocessBaselineBackend.is_available fail-closed probe (Change A t2)"
```

---

### Task 3: Stub worker + `predict` end-to-end through the seam

**Files:**
- Create: `scripts/baselines/stub_worker.py`
- Modify: `src/alive/compose/baseline_subprocess.py` (add `predict`)
- Test: `tests/alive/compose/test_baseline_subprocess.py`

**Interfaces:**
- Consumes: `BaselineAdapter`, `BaselineTrainingContext` from `baselines_combo.py`; `write_payload`/`read_payload`/`write_predictions`/`read_predictions` from Task 1.
- Produces: `SubprocessBaselineBackend.predict(context, pair_ids, response_dim) -> dict[tuple[str,str], np.ndarray]` — scans the serialized payload for sealed refs, writes it to a fresh temp `work_dir`, runs `<env_python> <worker_script> --in <work_dir> --out <preds>`, returns `read_predictions`. The **stub worker** returns, per requested pair `(g,h)`, the additive δ `singles_response[g] + singles_response[h]` (deterministic; ignores `seed` beyond recording it).

- [ ] **Step 1: Write the failing end-to-end + determinism + leakage tests**

```python
# add to tests/alive/compose/test_baseline_subprocess.py
from pathlib import Path

from alive.compose.baselines_combo import BaselineAdapter, BaselineTrainingContext

_STUB = str(Path(__file__).resolve().parents[3] / "scripts" / "baselines" / "stub_worker.py")


def _context() -> BaselineTrainingContext:
    return BaselineTrainingContext(
        allowed_roles=frozenset({"singles", "combo_calibration"}),
        pair_manifest_checksum="deadbeef",
        response_space_checksum="cafe",
        training_pair_ids=(("B", "C"),),
        single_gene_ids=("A", "B", "C"),
    )


def _backend() -> SubprocessBaselineBackend:
    return SubprocessBaselineBackend(
        name="stub", env_python=sys.executable, worker_script=_STUB, import_name="json"
    )


def test_predict_end_to_end_through_adapter(tmp_path):
    be = _backend()
    be._payload = _payload()  # test injects the fit-role payload (see Step 3 note)
    adapter = BaselineAdapter(name="stub", backend=be)
    out = adapter.predict(_context(), [("A", "B"), ("A", "C")], 3)
    assert set(out) == {("A", "B"), ("A", "C")}
    # additive stub: delta(A,B) = singles[A] + singles[B]
    np.testing.assert_allclose(out[("A", "B")], np.array([0.5, 0.7, 0.9]))


def test_predict_is_deterministic(tmp_path):
    be1, be2 = _backend(), _backend()
    be1._payload = _payload(); be2._payload = _payload()
    a = BaselineAdapter(name="stub", backend=be1).predict(_context(), [("A", "B")], 3)
    b = BaselineAdapter(name="stub", backend=be2).predict(_context(), [("A", "B")], 3)
    np.testing.assert_allclose(a[("A", "B")], b[("A", "B")])


def test_payload_with_sealed_token_is_refused():
    be = _backend()
    bad = _payload(); bad["single_gene_ids"] = ["A", "sealed_double_unseen", "C"]
    be._payload = bad
    with pytest.raises(ValueError, match="sealed"):
        be.predict(_context(), [("A", "B")], 3)
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/alive/compose/test_baseline_subprocess.py -k "end_to_end or deterministic or sealed_token" -q`
Expected: FAIL (`predict` not implemented / stub worker missing).

- [ ] **Step 3: Implement `predict` + the stub worker**

Add `predict` to `SubprocessBaselineBackend` (the `_payload` attribute carries the fit-role payload the caller/Phase-2a assembles; a later integration task wires the real assembly — here tests set it directly):

```python
# add to src/alive/compose/baseline_subprocess.py
import tempfile
from collections.abc import Sequence

from alive.compose.baselines_combo import _assert_no_sealed_reference

# in SubprocessBaselineBackend:
    _payload: dict | None = field(default=None, init=False, repr=False)

    def predict(self, context, pair_ids, response_dim):
        if self._payload is None:
            raise PayloadError(f"{self.name} backend has no fit-role payload assigned")
        payload = dict(self._payload)
        payload["pair_ids"] = [list(p) for p in pair_ids]
        payload["response_dim"] = int(response_dim)
        _assert_no_sealed_reference(payload)  # fit-role-only guard on the payload
        with tempfile.TemporaryDirectory() as work_dir:
            write_payload(work_dir, payload)
            out = f"{work_dir}/preds"
            r = subprocess.run(
                [self.env_python, self.worker_script, "--in", work_dir, "--out", out],
                capture_output=True, text=True, timeout=1800,
            )
            if r.returncode != 0:
                raise BaselineUnavailable(f"{self.name} worker failed: {r.stderr[-500:]}")
            return read_predictions(out)
```

Add the import at the top: `from alive.compose.baselines_combo import BaselineUnavailable`.

```python
# scripts/baselines/stub_worker.py
"""SYNTHETIC-ONLY deterministic additive-delta stub worker (protocol reference).

Runs in any python; predicts, per requested pair (g,h), the additive delta
singles_response[g] + singles_response[h] projected trivially to response_dim.
The real gears/cpa workers replace this under the locked envs (pod-only).
"""
from __future__ import annotations

import argparse

import numpy as np

from alive.compose.baseline_subprocess import read_payload, write_predictions


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="work_dir", required=True)
    ap.add_argument("--out", dest="out", required=True)
    a = ap.parse_args()
    p = read_payload(a.work_dir)
    ids = list(p["single_gene_ids"])
    singles = np.asarray(p["singles_response"], dtype=float)
    idx = {g: i for i, g in enumerate(ids)}
    dim = int(p["response_dim"])
    preds = {}
    for g, h in p["pair_ids"]:
        vec = singles[idx[g]] + singles[idx[h]]
        preds[(g, h)] = vec[:dim]
    write_predictions(a.out, preds)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/alive/compose/test_baseline_subprocess.py -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/baseline_subprocess.py scripts/baselines/stub_worker.py tests/alive/compose/test_baseline_subprocess.py
git commit -m "feat(compose): subprocess predict + deterministic stub worker, end-to-end (Change A t3)"
```

---

### Task 4: Fail-closed — unavailable backend ⇒ `BaselineUnavailable` ⇒ `FreezeError`

**Files:**
- Test: `tests/alive/compose/test_baseline_failclosed.py`

**Interfaces:**
- Consumes: `BaselineAdapter`, `BaselineUnavailable` (`baselines_combo.py`); `FreezeError`, `REQUIRED_METHODS`, the freeze-predictions entry point (`freeze.py`); `SubprocessBaselineBackend`.
- This task asserts the terminal state (the spec-review med finding): an unavailable deep backend must NOT be silently skipped — it raises `BaselineUnavailable`, and when its (absent) predictions reach roster assembly the result is a `FreezeError`, never a partial roster.

- [ ] **Step 1: Write the failing tests**

```python
# tests/alive/compose/test_baseline_failclosed.py
"""SYNTHETIC-ONLY: fail-closed terminal state for an unavailable deep backend."""
from __future__ import annotations

import sys

import pytest

from alive.compose.baseline_subprocess import SubprocessBaselineBackend
from alive.compose.baselines_combo import BaselineAdapter, BaselineTrainingContext, BaselineUnavailable


def _context() -> BaselineTrainingContext:
    return BaselineTrainingContext(
        allowed_roles=frozenset({"singles", "combo_calibration"}),
        pair_manifest_checksum="d", response_space_checksum="c",
        training_pair_ids=(("B", "C"),), single_gene_ids=("A", "B", "C"),
    )


def test_unavailable_backend_raises_baseline_unavailable():
    be = SubprocessBaselineBackend(
        name="gears", env_python=sys.executable, worker_script="x",
        import_name="definitely_not_a_real_module_xyz",
    )
    adapter = BaselineAdapter(name="gears", backend=be)
    with pytest.raises(BaselineUnavailable):
        adapter.predict(_context(), [("A", "B")], 3)
```

A second test asserts the absent-prediction path yields `FreezeError` at roster assembly. `freeze.REQUIRED_METHODS` includes `"gears"` and `"cpa"`; the roster-completeness enforcement is `freeze._validate_role_predictions` (called by the public `FrozenPredictionBundle.create`), which raises `FreezeError` matching `"missing"` when a roster method has no predictions. Assert that omitting `"gears"` (simulating its `BaselineUnavailable`) raises:

```python
import numpy as np

from alive.compose.freeze import REQUIRED_METHODS, FreezeError, _validate_role_predictions


def test_incomplete_roster_after_unavailable_backend_raises_freezeerror():
    # An unavailable deep backend (e.g. gears) contributes NO predictions; the
    # roster-completeness check must then raise FreezeError, never accept a
    # partial roster (the fail-closed terminal state — see spec-review med finding).
    pair = ("A", "B")  # canonical (min, max)
    vec = np.zeros(3)
    preds = {m: {pair: vec} for m in REQUIRED_METHODS if m != "gears"}
    with pytest.raises(FreezeError, match="missing"):
        _validate_role_predictions("sealed_double_unseen", REQUIRED_METHODS, (pair,), preds, 3)
```

(This directly exercises the enforcement point. If a reviewer prefers the public `FrozenPredictionBundle.create` path, that is a heavier integration test; the private-function assertion here is deliberately narrow and self-contained.)

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/alive/compose/test_baseline_failclosed.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

No production code should be needed — this task VERIFIES existing fail-closed behavior. If the second test cannot be expressed against the real `freeze.py` API without a code change, STOP and report to the controller (the plan assumed roster-completeness is already enforced in `freeze.py`); do not add speculative production code.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/alive/compose/test_baseline_failclosed.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/alive/compose/test_baseline_failclosed.py
git commit -m "test(compose): fail-closed unavailable backend -> BaselineUnavailable -> FreezeError (Change A t4)"
```

---

## Out of scope (pod-only, deferred to the pod runbook)

- Real `scripts/baselines/gears_worker.py` / `cpa_worker.py` (import gears/cpa, GO-graph + gene2go for GEARS, CPA setup, published-default fit). These are validated on the A100 in the locked envs, then a mini-fixture end-to-end, then the sealed run.
- The Phase-2a assembly that constructs the real fit-role payload from live Norman δ/PCA and injects it into `SubprocessBaselineBackend` (the tests here set `_payload` directly). If that wiring belongs in this milestone, add it as a follow-up task once the payload's exact producer is confirmed against `phase2a.py`.

## Notes for the executor

- Confirm `_assert_no_sealed_reference` is importable and scans plain dicts/lists (it does — `baselines_combo.py`); the payload is a plain dict of JSON scalars/lists, and numpy arrays are absent from it (arrays are lists), so the scan reaches every string.
- Do not add gears/cpa to `pyproject.toml`. The only new runtime code path is `subprocess`.
- After all tasks: `uv run pytest tests/alive/compose -q` and `uv run ruff check src tests && uv run ruff format --check src tests` must be green, then gate this increment with the `science-dev` loop profile.
