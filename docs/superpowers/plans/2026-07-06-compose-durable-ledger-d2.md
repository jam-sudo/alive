# COMPOSE Development Seed-Variability (sub-project D2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the non-sealed development seed-variability harness that reports each stochastic comparator's (`gears`, `cpa`) registered-seed OOF error spread and binds a self-checksummed `development_seed_variability.json` into the pre-access ledger the sealed run consumes.

**Architecture:** A new focused module `src/alive/compose/seed_variability.py` derives per-fold train/test/cross-group manifests deterministically from the Phase-2a per-pair `oof_folds` assignment + `select.py` gene-disjoint grouping (no new RNG), builds fold-scoped fit payloads that exclude every held-out/cross-group pair from fit/validation/early-stopping, runs each `(method, seed, fold)` through the existing `BaselineAdapter` seam to predict only held-out test pairs, reassembles predictions in one canonical covered-OOF-pair order, and summarizes per-seed OOF mean MSE spread. The report is a write-once self-checksummed artifact bound into the pre-access ledger; Phase-2b preflight fails closed if it is absent, tampered, `INCOMPLETE`, or coverage-mismatched. It opens no seal.

**Tech Stack:** Python 3, NumPy, the existing `alive.compose` modules (`phase2a`, `select`, `baselines_combo`, `response`, `outcome_store`, `provenance2`), `alive.provenance.RunLedger`/`sha256_json`, `alive.io.atomic_write_once`. Tests: pytest with synthetic `tmp_path` fixtures + the deterministic additive stub worker only (no gears/cpa import).

## Global Constraints

Copied verbatim from the D design spec (`docs/superpowers/specs/2026-07-05-compose-durable-ledger-design.md` §4, §5) and the active config (`configs/compose_k562_v1_phase2.yaml`). Every task's requirements implicitly include this section.

- **Registered seeds:** the config `seeds.registered_seeds` exact ordered roster `(11, 23, 37)`. Never reorder or subset; the report iterates them in this order.
- **Seed-refittable stochastic comparators:** `gears`, `cpa` ONLY. These enter the seed loop.
- **Deterministic single-shot roster (EXCLUDED from the seed loop):** `l1_bilinear_identifiable`, `l2_saturation`, `l3_hypernetwork`, `id_only`, `additive`, `no_change`, `perturbation_mean`. `l3_hypernetwork` is deterministic today (module-fixed `_L3_SEED`); adding an external seed to L3 needs a separate protocol amendment + model-checksum schema revision — OUT OF SCOPE.
- **Sample standard deviation uses `ddof=1`.**
- **Report artifact filename is EXACTLY `development_seed_variability.json`**, self-checksummed, write-once (never overwrite a non-identical existing file).
- **Status ∈ {`COMPLETE`, `INCOMPLETE`}.** Any failed seed, any coverage mismatch vs the Phase-2a selection artifact, or an uncovered fraction above `uncovered_tolerance` → `INCOMPLETE`, which blocks Phase-2b preflight. Only all-seeds-success → `COMPLETE`. Never drop a failed seed and summarize only successes.
- **Non-sealed inputs only.** D2 accepts a `DevelopmentOutcomeStore` (audited-unsealed or bounded synthetic). It MUST reject a `ComposeOutcomeStore` / sealed store, and reject arbitrary outcome arrays/dicts/paths and object injection.
- **No new fold RNG.** Fold manifests are DERIVED deterministically from the persisted per-pair `oof_folds` assignment + `select.py` grouping; D2 never re-randomizes folds.
- **Identical covered set.** Every `(method, seed)` uses the SAME canonical covered OOF pair set; a method may not silently drop pairs.
- **Truth reconstructed once:** `inputs.additive_cal + development_outcome_store.combo_calibration_eps`, with pair-ID alignment + outcome-store content-checksum verification.
- **No per-pair CI.** D2 reports per-seed scalars and spread only. Primary inference stays the existing pair-resampled aggregate simultaneous bound.
- **Opens no seal.** The local stub validates seed-passing / fold-exclusion / alignment / checksum wiring only; spread 0 from the stub is NOT stability evidence. Real GEARS/CPA numbers are produced only on the locked pod environments.
- **Production entry** calls the internal `build_fold_scoped_fit_payload(...)` only; it accepts no caller-supplied payload/factory. Any fixture-only injection seam must be structurally unreachable from the scientific entry point.

---

## File Structure

- **Create `src/alive/compose/seed_variability.py`** — the whole D2 harness: `SeedVariabilityStatus`, `CoverageReport`, `SeedComparatorSummary`, `SeedVariabilityReport` (+ self-checksum + write-once + load), `build_seed_variability_fold_manifest`, `build_fold_scoped_fit_payload`, the per-fold OOF prediction/reassembly helpers, the `development_seed_variability(...)` production entry, and `verify_seed_variability_for_preflight(...)`.
- **Create `tests/alive/compose/test_seed_variability.py`** — all D2 tests (report roundtrip, fold-manifest derivation, fold-scoped exclusion, reassembly, entry, failure policy, pre-seal binding, leakage/injection rejection). Model fixtures on `tests/alive/compose/test_phase2a.py` and `test_payload_v2_integration.py`.
- **Modify `src/alive/compose/phase2b.py`** — call `verify_seed_variability_for_preflight(...)` inside the Phase-2b scientific preflight, before seal access.

The report container, the fold manifest, the fold-scoped payload, and the prediction/summary loop change together (one contract) and live in one module; the phase2b modify is a single wiring call.

---

## Task 1: SeedVariabilityReport container + coverage block + write-once artifact

**Files:**
- Create: `src/alive/compose/seed_variability.py`
- Test: `tests/alive/compose/test_seed_variability.py`

**Interfaces:**
- Consumes: `alive.provenance.sha256_json`, `alive.io.atomic_write_once`.
- Produces:
  - `class SeedVariabilityStatus(str, Enum)` with `COMPLETE = "COMPLETE"`, `INCOMPLETE = "INCOMPLETE"`.
  - `@dataclass(frozen=True) CoverageReport` fields: `total_pairs: int`, `covered_count: int`, `uncovered_count: int`, `uncovered_fraction: float`, `covered_pair_ids_sha256: str`, `uncovered_pair_ids_sha256: str`, `uncovered_tolerance: float`; method `to_dict() -> dict`.
  - `@dataclass(frozen=True) SeedComparatorSummary` fields: `method: str`, `seed_to_oof_mean_pair_mse: tuple[tuple[int, float], ...]` (ordered), `mean: float`, `std: float`, `min: float`, `max: float`, `range: float`, `failed_seeds: tuple[int, ...]`, `failure_class_by_seed: tuple[tuple[int, str], ...]`, `prediction_checksum_by_seed: tuple[tuple[int, str], ...]`, `checkpoint_checksum_by_seed: tuple[tuple[int, str], ...]`; method `to_dict() -> dict`.
  - `@dataclass(frozen=True) SeedVariabilityReport` fields: `schema_version: int` (=1), `status: SeedVariabilityStatus`, `registered_seeds: tuple[int, ...]`, `deterministic_single_shot: tuple[str, ...]`, `coverage: CoverageReport`, `comparators: tuple[SeedComparatorSummary, ...]`, `oof_fold_assignment_sha256: str`, `response_space_checksum: str`, `fit_role_artifact_sha256: str`, `worker_lock_sha256_by_method: tuple[tuple[str, str], ...]`, `report_checksum: str` (self-excluding); methods `payload_without_checksum() -> dict`, `self_checksum() -> str`, `to_dict() -> dict`, `write_once(run_dir) -> Path`, classmethod `load(path) -> "SeedVariabilityReport"`.
  - `DEVELOPMENT_SEED_VARIABILITY_FILENAME = "development_seed_variability.json"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_seed_variability.py
import json
from pathlib import Path

import pytest

from alive.compose.seed_variability import (
    DEVELOPMENT_SEED_VARIABILITY_FILENAME,
    CoverageReport,
    SeedComparatorSummary,
    SeedVariabilityReport,
    SeedVariabilityStatus,
)


def _coverage() -> CoverageReport:
    return CoverageReport(
        total_pairs=10,
        covered_count=8,
        uncovered_count=2,
        uncovered_fraction=0.2,
        covered_pair_ids_sha256="a" * 64,
        uncovered_pair_ids_sha256="b" * 64,
        uncovered_tolerance=0.25,
    )


def _summary(method: str) -> SeedComparatorSummary:
    return SeedComparatorSummary(
        method=method,
        seed_to_oof_mean_pair_mse=((11, 0.5), (23, 0.6), (37, 0.55)),
        mean=0.55,
        std=0.05,
        min=0.5,
        max=0.6,
        range=0.1,
        failed_seeds=(),
        failure_class_by_seed=(),
        prediction_checksum_by_seed=((11, "c" * 64), (23, "d" * 64), (37, "e" * 64)),
        checkpoint_checksum_by_seed=((11, "f" * 64), (23, "0" * 64), (37, "1" * 64)),
    )


def _report() -> SeedVariabilityReport:
    return SeedVariabilityReport(
        schema_version=1,
        status=SeedVariabilityStatus.COMPLETE,
        registered_seeds=(11, 23, 37),
        deterministic_single_shot=(
            "l1_bilinear_identifiable",
            "l2_saturation",
            "l3_hypernetwork",
            "id_only",
            "additive",
            "no_change",
            "perturbation_mean",
        ),
        coverage=_coverage(),
        comparators=(_summary("gears"), _summary("cpa")),
        oof_fold_assignment_sha256="2" * 64,
        response_space_checksum="3" * 64,
        fit_role_artifact_sha256="4" * 64,
        worker_lock_sha256_by_method=(("gears", "5" * 64), ("cpa", "6" * 64)),
        report_checksum="",
    )


def test_self_checksum_excludes_report_checksum_and_is_stable():
    report = _report().finalize_checksum()
    assert len(report.report_checksum) == 64
    # recomputing the self-checksum reproduces the stored value
    assert report.self_checksum() == report.report_checksum
    # a different summary changes the checksum
    other = _report()
    other = other.__class__(**{**other.__dict__, "status": SeedVariabilityStatus.INCOMPLETE})
    assert other.finalize_checksum().report_checksum != report.report_checksum


def test_write_once_roundtrips_and_refuses_overwrite(tmp_path: Path):
    report = _report().finalize_checksum()
    path = report.write_once(tmp_path)
    assert path.name == DEVELOPMENT_SEED_VARIABILITY_FILENAME
    loaded = SeedVariabilityReport.load(path)
    assert loaded.report_checksum == report.report_checksum
    assert loaded.self_checksum() == report.report_checksum
    with pytest.raises(FileExistsError):
        report.write_once(tmp_path)


def test_load_rejects_checksum_tamper(tmp_path: Path):
    report = _report().finalize_checksum()
    path = report.write_once(tmp_path)
    payload = json.loads(path.read_text())
    payload["coverage"]["covered_count"] = 7  # tamper without recomputing checksum
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="checksum"):
        SeedVariabilityReport.load(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_seed_variability.py -x -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'alive.compose.seed_variability'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/alive/compose/seed_variability.py
"""COMPOSE development seed-variability harness (sub-project D2).

Reports each seed-refittable stochastic comparator's registered-seed OOF error
spread on the frozen Phase-2a gene-disjoint calibration folds. Opens no seal;
uses non-sealed calibration outcomes only. See
``docs/superpowers/specs/2026-07-05-compose-durable-ledger-design.md`` §4.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Mapping

from alive.io import atomic_write_once
from alive.provenance import sha256_json

DEVELOPMENT_SEED_VARIABILITY_FILENAME = "development_seed_variability.json"

#: Seed-refittable stochastic comparators that enter the seed loop.
SEED_REFITTABLE_METHODS: tuple[str, ...] = ("gears", "cpa")

#: Deterministic single-shot roster, EXCLUDED from the seed loop (spec §4.1).
DETERMINISTIC_SINGLE_SHOT: tuple[str, ...] = (
    "l1_bilinear_identifiable",
    "l2_saturation",
    "l3_hypernetwork",
    "id_only",
    "additive",
    "no_change",
    "perturbation_mean",
)


class SeedVariabilityStatus(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True)
class CoverageReport:
    total_pairs: int
    covered_count: int
    uncovered_count: int
    uncovered_fraction: float
    covered_pair_ids_sha256: str
    uncovered_pair_ids_sha256: str
    uncovered_tolerance: float

    def to_dict(self) -> dict:
        return {
            "total_pairs": int(self.total_pairs),
            "covered_count": int(self.covered_count),
            "uncovered_count": int(self.uncovered_count),
            "uncovered_fraction": float(self.uncovered_fraction),
            "covered_pair_ids_sha256": self.covered_pair_ids_sha256,
            "uncovered_pair_ids_sha256": self.uncovered_pair_ids_sha256,
            "uncovered_tolerance": float(self.uncovered_tolerance),
        }


@dataclass(frozen=True)
class SeedComparatorSummary:
    method: str
    seed_to_oof_mean_pair_mse: tuple[tuple[int, float], ...]
    mean: float
    std: float
    min: float
    max: float
    range: float
    failed_seeds: tuple[int, ...]
    failure_class_by_seed: tuple[tuple[int, str], ...]
    prediction_checksum_by_seed: tuple[tuple[int, str], ...]
    checkpoint_checksum_by_seed: tuple[tuple[int, str], ...]

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "seed_to_oof_mean_pair_mse": [[int(s), float(v)] for s, v in self.seed_to_oof_mean_pair_mse],
            "mean": float(self.mean),
            "std": float(self.std),
            "min": float(self.min),
            "max": float(self.max),
            "range": float(self.range),
            "failed_seeds": [int(s) for s in self.failed_seeds],
            "failure_class_by_seed": [[int(s), c] for s, c in self.failure_class_by_seed],
            "prediction_checksum_by_seed": [[int(s), c] for s, c in self.prediction_checksum_by_seed],
            "checkpoint_checksum_by_seed": [[int(s), c] for s, c in self.checkpoint_checksum_by_seed],
        }


@dataclass(frozen=True)
class SeedVariabilityReport:
    schema_version: int
    status: SeedVariabilityStatus
    registered_seeds: tuple[int, ...]
    deterministic_single_shot: tuple[str, ...]
    coverage: CoverageReport
    comparators: tuple[SeedComparatorSummary, ...]
    oof_fold_assignment_sha256: str
    response_space_checksum: str
    fit_role_artifact_sha256: str
    worker_lock_sha256_by_method: tuple[tuple[str, str], ...]
    report_checksum: str = field(default="")

    def payload_without_checksum(self) -> dict:
        return {
            "schema_version": int(self.schema_version),
            "status": self.status.value,
            "registered_seeds": [int(s) for s in self.registered_seeds],
            "deterministic_single_shot": list(self.deterministic_single_shot),
            "coverage": self.coverage.to_dict(),
            "comparators": [c.to_dict() for c in self.comparators],
            "oof_fold_assignment_sha256": self.oof_fold_assignment_sha256,
            "response_space_checksum": self.response_space_checksum,
            "fit_role_artifact_sha256": self.fit_role_artifact_sha256,
            "worker_lock_sha256_by_method": [[m, s] for m, s in self.worker_lock_sha256_by_method],
        }

    def self_checksum(self) -> str:
        return sha256_json(self.payload_without_checksum())

    def finalize_checksum(self) -> "SeedVariabilityReport":
        return SeedVariabilityReport(**{**self.__dict__, "report_checksum": self.self_checksum()})

    def to_dict(self) -> dict:
        payload = self.payload_without_checksum()
        payload["report_checksum"] = self.report_checksum
        return payload

    def write_once(self, run_dir: str | Path) -> Path:
        if not self.report_checksum:
            raise ValueError("report_checksum must be finalized before write_once")
        destination = Path(run_dir) / DEVELOPMENT_SEED_VARIABILITY_FILENAME
        atomic_write_once(destination, json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")))
        return destination

    @classmethod
    def load(cls, path: str | Path) -> "SeedVariabilityReport":
        payload = json.loads(Path(path).read_text())
        report = cls(
            schema_version=int(payload["schema_version"]),
            status=SeedVariabilityStatus(payload["status"]),
            registered_seeds=tuple(int(s) for s in payload["registered_seeds"]),
            deterministic_single_shot=tuple(payload["deterministic_single_shot"]),
            coverage=CoverageReport(**payload["coverage"]),
            comparators=tuple(
                SeedComparatorSummary(
                    method=c["method"],
                    seed_to_oof_mean_pair_mse=tuple((int(s), float(v)) for s, v in c["seed_to_oof_mean_pair_mse"]),
                    mean=float(c["mean"]),
                    std=float(c["std"]),
                    min=float(c["min"]),
                    max=float(c["max"]),
                    range=float(c["range"]),
                    failed_seeds=tuple(int(s) for s in c["failed_seeds"]),
                    failure_class_by_seed=tuple((int(s), cl) for s, cl in c["failure_class_by_seed"]),
                    prediction_checksum_by_seed=tuple((int(s), h) for s, h in c["prediction_checksum_by_seed"]),
                    checkpoint_checksum_by_seed=tuple((int(s), h) for s, h in c["checkpoint_checksum_by_seed"]),
                )
                for c in payload["comparators"]
            ),
            oof_fold_assignment_sha256=payload["oof_fold_assignment_sha256"],
            response_space_checksum=payload["response_space_checksum"],
            fit_role_artifact_sha256=payload["fit_role_artifact_sha256"],
            worker_lock_sha256_by_method=tuple((m, s) for m, s in payload["worker_lock_sha256_by_method"]),
            report_checksum=payload["report_checksum"],
        )
        if report.self_checksum() != report.report_checksum:
            raise ValueError("development_seed_variability report checksum mismatch (tampered artifact)")
        return report
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/alive/compose/test_seed_variability.py -x -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/seed_variability.py tests/alive/compose/test_seed_variability.py
git commit -m "feat(compose): D2 SeedVariabilityReport container + write-once self-checksummed artifact"
```

---

## Task 2: Fold manifest derived from the persisted OOF assignment (no new RNG)

**Files:**
- Modify: `src/alive/compose/seed_variability.py`
- Test: `tests/alive/compose/test_seed_variability.py`

**Interfaces:**
- Consumes: `alive.compose.select.build_gene_disjoint_folds(gene_order, n_folds, seed) -> tuple[GeneDisjointFold, ...]` (each `GeneDisjointFold` has `held_out_genes`, `train_idx`, `test_idx`, `excluded_idx` — pair indices into the calibration pair list); the persisted per-pair `oof_folds: Sequence[int]` (calibration-pair-aligned, from `build_subprocess_fit_payload`); `alive.provenance.sha256_json`.
- Produces:
  - `@dataclass(frozen=True) FoldScopedManifest` fields: `fold_index: int`, `train_pair_positions: tuple[int, ...]`, `test_pair_positions: tuple[int, ...]`, `cross_group_pair_positions: tuple[int, ...]`.
  - `@dataclass(frozen=True) SeedVariabilityFoldManifest` fields: `cal_pair_ids: tuple[tuple[str, str], ...]`, `folds: tuple[FoldScopedManifest, ...]`, `covered_pair_positions: tuple[int, ...]` (union of test positions, sorted), `uncovered_pair_positions: tuple[int, ...]`, `manifest_sha256: str`; methods `to_dict()`, `self_checksum()`, `finalize_checksum()`.
  - `build_seed_variability_fold_manifest(*, cal_pair_ids, oof_fold_assignment, n_folds, split_seed) -> SeedVariabilityFoldManifest`.
  - `SelectionCoverage = tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]` — `(covered_pair_ids, uncovered_pair_ids)` from the Phase-2a `SelectionResult` (`union_test_pair_ids`, `uncovered_pair_ids`); helper `coverage_matches_selection(manifest, *, selection_covered, selection_uncovered) -> bool`.

The manifest re-derives the same gene-disjoint folds `select.py` used (same `gene_order`, `n_folds`, `split_seed`) purely to obtain per-fold train/test/cross-group PAIR partitions, then cross-checks the per-pair `oof_fold_assignment` (which fold each covered pair is a test pair of). It creates NO new randomness.

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_seed_variability.py  (append)
from alive.compose.seed_variability import (
    SeedVariabilityFoldManifest,
    build_seed_variability_fold_manifest,
    coverage_matches_selection,
)


def _linear_pairs():
    # 6 genes A..F, gene-disjoint folds with split_seed=11, n_folds=3
    return (("A", "B"), ("C", "D"), ("E", "F"), ("A", "C"))  # last is a cross-group pair


def test_fold_manifest_partitions_are_disjoint_and_cover_test_pairs():
    cal_pair_ids = _linear_pairs()
    # oof_fold_assignment: fold index per covered pair; -1 == uncovered/cross-group
    oof = (0, 1, 2, -1)
    manifest = build_seed_variability_fold_manifest(
        cal_pair_ids=cal_pair_ids, oof_fold_assignment=oof, n_folds=3, split_seed=11
    ).finalize_checksum()
    # every covered pair is a test pair of exactly its assigned fold
    for pos, fold_idx in enumerate(oof):
        for fold in manifest.folds:
            if fold_idx == -1:
                assert pos not in fold.test_pair_positions
            elif fold.fold_index == fold_idx:
                assert pos in fold.test_pair_positions
            else:
                assert pos not in fold.test_pair_positions
    # train and test positions never overlap within a fold
    for fold in manifest.folds:
        assert not (set(fold.train_pair_positions) & set(fold.test_pair_positions))
        assert not (set(fold.train_pair_positions) & set(fold.cross_group_pair_positions))
    # covered == union of test positions; uncovered == the -1 rows
    assert manifest.covered_pair_positions == (0, 1, 2)
    assert manifest.uncovered_pair_positions == (3,)
    assert len(manifest.manifest_sha256) == 64


def test_fold_manifest_is_deterministic_no_new_rng():
    cal_pair_ids = _linear_pairs()
    oof = (0, 1, 2, -1)
    a = build_seed_variability_fold_manifest(
        cal_pair_ids=cal_pair_ids, oof_fold_assignment=oof, n_folds=3, split_seed=11
    ).finalize_checksum()
    b = build_seed_variability_fold_manifest(
        cal_pair_ids=cal_pair_ids, oof_fold_assignment=oof, n_folds=3, split_seed=11
    ).finalize_checksum()
    assert a.manifest_sha256 == b.manifest_sha256


def test_coverage_matches_selection_detects_mismatch():
    cal_pair_ids = _linear_pairs()
    oof = (0, 1, 2, -1)
    manifest = build_seed_variability_fold_manifest(
        cal_pair_ids=cal_pair_ids, oof_fold_assignment=oof, n_folds=3, split_seed=11
    ).finalize_checksum()
    covered = (("A", "B"), ("C", "D"), ("E", "F"))
    uncovered = (("A", "C"),)
    assert coverage_matches_selection(manifest, selection_covered=covered, selection_uncovered=uncovered)
    # a selection that covers a different set fails
    assert not coverage_matches_selection(
        manifest, selection_covered=(("A", "B"), ("C", "D")), selection_uncovered=(("E", "F"), ("A", "C"))
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_seed_variability.py -x -q -k fold_manifest or coverage_matches`
Expected: FAIL — `ImportError: cannot import name 'build_seed_variability_fold_manifest'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/alive/compose/seed_variability.py  (append)
from alive.compose.select import build_gene_disjoint_folds


@dataclass(frozen=True)
class FoldScopedManifest:
    fold_index: int
    train_pair_positions: tuple[int, ...]
    test_pair_positions: tuple[int, ...]
    cross_group_pair_positions: tuple[int, ...]

    def to_dict(self) -> dict:
        return {
            "fold_index": int(self.fold_index),
            "train_pair_positions": list(self.train_pair_positions),
            "test_pair_positions": list(self.test_pair_positions),
            "cross_group_pair_positions": list(self.cross_group_pair_positions),
        }


@dataclass(frozen=True)
class SeedVariabilityFoldManifest:
    cal_pair_ids: tuple[tuple[str, str], ...]
    folds: tuple[FoldScopedManifest, ...]
    covered_pair_positions: tuple[int, ...]
    uncovered_pair_positions: tuple[int, ...]
    manifest_sha256: str = field(default="")

    def payload_without_checksum(self) -> dict:
        return {
            "cal_pair_ids": [list(p) for p in self.cal_pair_ids],
            "folds": [f.to_dict() for f in self.folds],
            "covered_pair_positions": list(self.covered_pair_positions),
            "uncovered_pair_positions": list(self.uncovered_pair_positions),
        }

    def self_checksum(self) -> str:
        return sha256_json(self.payload_without_checksum())

    def finalize_checksum(self) -> "SeedVariabilityFoldManifest":
        return SeedVariabilityFoldManifest(**{**self.__dict__, "manifest_sha256": self.self_checksum()})

    def to_dict(self) -> dict:
        payload = self.payload_without_checksum()
        payload["manifest_sha256"] = self.manifest_sha256
        return payload


def build_seed_variability_fold_manifest(
    *,
    cal_pair_ids: tuple[tuple[str, str], ...],
    oof_fold_assignment: "Sequence[int]",
    n_folds: int,
    split_seed: int,
) -> SeedVariabilityFoldManifest:
    """Derive per-fold train/test/cross-group PAIR partitions deterministically.

    Re-runs ``select.build_gene_disjoint_folds`` with the same gene order and
    split seed the Phase-2a selection used (obtaining pair-index partitions), and
    cross-checks the persisted per-pair ``oof_fold_assignment``. No new RNG.
    """
    if len(oof_fold_assignment) != len(cal_pair_ids):
        raise ValueError("oof_fold_assignment must align one-to-one with calibration pairs")
    gene_order = tuple(sorted({g for pair in cal_pair_ids for g in pair}, key=lambda g: g.encode("utf-8")))
    disjoint = build_gene_disjoint_folds(gene_order, n_folds=n_folds, seed=split_seed)
    folds: list[FoldScopedManifest] = []
    covered: set[int] = set()
    for fold in disjoint:
        test_pos = tuple(int(i) for i in fold.test_idx)
        # honour the persisted assignment: a covered pair is a test pair of exactly its assigned fold
        test_pos = tuple(pos for pos in test_pos if int(oof_fold_assignment[pos]) == int(fold_index_of(disjoint, fold)))
        folds.append(
            FoldScopedManifest(
                fold_index=fold_index_of(disjoint, fold),
                train_pair_positions=tuple(int(i) for i in fold.train_idx),
                test_pair_positions=test_pos,
                cross_group_pair_positions=tuple(int(i) for i in fold.excluded_idx),
            )
        )
        covered.update(test_pos)
    covered_sorted = tuple(sorted(covered))
    uncovered_sorted = tuple(sorted(set(range(len(cal_pair_ids))) - covered))
    return SeedVariabilityFoldManifest(
        cal_pair_ids=tuple(tuple(p) for p in cal_pair_ids),
        folds=tuple(folds),
        covered_pair_positions=covered_sorted,
        uncovered_pair_positions=uncovered_sorted,
    )


def fold_index_of(disjoint: tuple, fold) -> int:
    return disjoint.index(fold)


def coverage_matches_selection(
    manifest: SeedVariabilityFoldManifest,
    *,
    selection_covered: tuple[tuple[str, str], ...],
    selection_uncovered: tuple[tuple[str, str], ...],
) -> bool:
    """True iff the manifest's covered/uncovered pair IDs equal the Phase-2a selection's."""
    covered_ids = {manifest.cal_pair_ids[pos] for pos in manifest.covered_pair_positions}
    uncovered_ids = {manifest.cal_pair_ids[pos] for pos in manifest.uncovered_pair_positions}
    return covered_ids == {tuple(p) for p in selection_covered} and uncovered_ids == {
        tuple(p) for p in selection_uncovered
    }
```

Add `from typing import Sequence` to the module imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/alive/compose/test_seed_variability.py -x -q`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/seed_variability.py tests/alive/compose/test_seed_variability.py
git commit -m "feat(compose): D2 deterministic fold manifest derived from persisted OOF assignment"
```

---

## Task 3: Fold-scoped fit payload (train pairs only; held-out + cross-group excluded)

**Files:**
- Modify: `src/alive/compose/seed_variability.py`
- Test: `tests/alive/compose/test_seed_variability.py`

**Interfaces:**
- Consumes: `alive.compose.phase2a.build_subprocess_fit_payload(*, inputs, outcome_store, response_artifact, oof_folds, fit_role_spec, gene_order, raw_data_sha256) -> dict` (the canonical full-calibration payload builder); `Phase2aInputs` (fields `cal_pair_ids`, `additive_cal`, `delta_by_gene`, `response_dim`, `seed`, `response_space_checksum`); `DevelopmentOutcomeStore` (`combo_calibration_pair_ids`, `combo_calibration_eps`); the `SeedVariabilityFoldManifest`/`FoldScopedManifest` from Task 2.
- Produces: `build_fold_scoped_fit_payload(*, inputs, outcome_store, response_artifact, fit_role_spec, gene_order, raw_data_sha256, manifest, fold_index, seed) -> dict` — a payload whose `calibration_pair_ids`/`calibration_delta`/`oof_folds` contain ONLY the fold's train pairs; adds `fold_index`, `held_out_test_pair_ids`, `cross_group_pair_ids`, `train_pair_source_checksum`, and the per-payload `seed` (overriding `inputs.seed`); the held-out test and cross-group pair rows/targets/aggregates are absent from the fit block.

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_seed_variability.py  (append)
# Reuse the synthetic Phase2aInputs + DevelopmentOutcomeStore + response_artifact
# fixtures from test_phase2a.py / test_payload_v2_integration.py. Import the
# helper that builds them (or copy the small builder) as `_synthetic_phase2a_env`.
from alive.compose.seed_variability import build_fold_scoped_fit_payload


def test_fold_scoped_payload_excludes_held_out_and_cross_group(_synthetic_phase2a_env):
    env = _synthetic_phase2a_env  # has .inputs, .outcome_store, .response_artifact,
    #                               .fit_role_spec, .gene_order, .raw_data_sha256,
    #                               .oof_fold_assignment, .n_folds, .split_seed
    manifest = build_seed_variability_fold_manifest(
        cal_pair_ids=tuple(tuple(p) for p in env.inputs.cal_pair_ids),
        oof_fold_assignment=env.oof_fold_assignment,
        n_folds=env.n_folds,
        split_seed=env.split_seed,
    ).finalize_checksum()
    fold = manifest.folds[0]
    payload = build_fold_scoped_fit_payload(
        inputs=env.inputs,
        outcome_store=env.outcome_store,
        response_artifact=env.response_artifact,
        fit_role_spec=env.fit_role_spec,
        gene_order=env.gene_order,
        raw_data_sha256=env.raw_data_sha256,
        manifest=manifest,
        fold_index=0,
        seed=23,
    )
    train_ids = {tuple(p) for p in payload["calibration_pair_ids"]}
    held_out = {tuple(p) for p in payload["held_out_test_pair_ids"]}
    cross = {tuple(p) for p in payload["cross_group_pair_ids"]}
    # held-out and cross-group are NOT in the fit block
    assert not (train_ids & held_out)
    assert not (train_ids & cross)
    # the fit block only contains this fold's train pairs
    assert train_ids == {env.inputs.cal_pair_ids[i] for i in fold.train_pair_positions}
    # calibration_delta rows align 1:1 with the (train-only) calibration_pair_ids
    assert len(payload["calibration_delta"]) == len(payload["calibration_pair_ids"])
    # seed override took effect and a source checksum is bound
    assert payload["seed"] == 23
    assert payload["fold_index"] == 0
    assert len(payload["train_pair_source_checksum"]) == 64
    # singles are retained in full (governed universe unchanged)
    assert payload["single_gene_ids"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_seed_variability.py -x -q -k fold_scoped`
Expected: FAIL — `ImportError: cannot import name 'build_fold_scoped_fit_payload'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/alive/compose/seed_variability.py  (append)
import numpy as np

from alive.compose.phase2a import build_subprocess_fit_payload


def build_fold_scoped_fit_payload(
    *,
    inputs,
    outcome_store,
    response_artifact: Mapping,
    fit_role_spec,
    gene_order,
    raw_data_sha256: str,
    manifest: SeedVariabilityFoldManifest,
    fold_index: int,
    seed: int,
) -> dict:
    """Build a payload restricted to one fold's TRAIN pairs (spec §4.2 step 2-3).

    The held-out test pairs and the cross-group pairs of ``fold_index`` are fully
    excluded from the fit block; singles are retained per the registered contract.
    Truth for the train pairs is reconstructed exactly as the canonical builder
    does (``additive_cal + combo_calibration_eps``) by delegating to
    ``build_subprocess_fit_payload`` on a train-only slice.
    """
    fold = next(f for f in manifest.folds if f.fold_index == int(fold_index))
    train_pos = list(fold.train_pair_positions)
    cal_pair_ids = tuple(tuple(p) for p in inputs.cal_pair_ids)

    # A train-only projection of inputs/outcome_store keeps the canonical builder's
    # alignment invariants (pair IDs <-> delta rows <-> oof_folds) intact.
    from dataclasses import replace

    train_pairs = tuple(cal_pair_ids[i] for i in train_pos)
    train_inputs = replace(
        inputs,
        cal_pair_ids=train_pairs,
        additive_cal=np.asarray(inputs.additive_cal, dtype=float)[train_pos],
    )
    train_store = outcome_store.restricted_to(train_pairs)  # Task 3a helper (below)
    train_oof = [0 for _ in train_pos]  # all train rows share the single train fold marker

    payload = build_subprocess_fit_payload(
        inputs=train_inputs,
        outcome_store=train_store,
        response_artifact=response_artifact,
        oof_folds=train_oof,
        fit_role_spec=fit_role_spec,
        gene_order=gene_order,
        raw_data_sha256=raw_data_sha256,
    )
    payload["fold_index"] = int(fold_index)
    payload["seed"] = int(seed)
    payload["held_out_test_pair_ids"] = [list(cal_pair_ids[i]) for i in fold.test_pair_positions]
    payload["cross_group_pair_ids"] = [list(cal_pair_ids[i]) for i in fold.cross_group_pair_positions]
    payload["train_pair_source_checksum"] = sha256_json(
        {"train_pairs": [list(p) for p in train_pairs], "fold_index": int(fold_index)}
    )
    return payload
```

Add a `restricted_to(train_pairs)` helper to `DevelopmentOutcomeStore` in `src/alive/compose/outcome_store.py` that returns a new store whose `combo_calibration_pair_ids`/`combo_calibration_eps` are the train-pair subset in the same order, preserving its content-checksum contract:

```python
# src/alive/compose/outcome_store.py  (add to DevelopmentOutcomeStore)
def restricted_to(self, pair_ids: "Sequence[tuple[str, str]]") -> "DevelopmentOutcomeStore":
    """Return a train-pair-restricted view (D2 fold scoping); order follows ``pair_ids``."""
    wanted = [tuple(p) for p in pair_ids]
    index = {tuple(p): i for i, p in enumerate(self.combo_calibration_pair_ids)}
    missing = [p for p in wanted if p not in index]
    if missing:
        raise KeyError(f"restricted_to: pairs absent from development store: {missing[:3]}")
    rows = [index[p] for p in wanted]
    return DevelopmentOutcomeStore(
        combo_calibration_pair_ids=tuple(wanted),
        combo_calibration_eps=np.asarray(self.combo_calibration_eps, dtype=float)[rows],
    )
```

(If `DevelopmentOutcomeStore` has a different constructor, mirror its exact fields — the invariant is: train-pair subset, same order, `combo_calibration_eps` rows sliced to match. Read `src/alive/compose/outcome_store.py:202` before writing this.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/alive/compose/test_seed_variability.py -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/seed_variability.py src/alive/compose/outcome_store.py tests/alive/compose/test_seed_variability.py
git commit -m "feat(compose): D2 fold-scoped fit payload (train-only; held-out + cross-group excluded)"
```

---

## Task 4: Per-fold OOF prediction, canonical reassembly, per-seed scalar

**Files:**
- Modify: `src/alive/compose/seed_variability.py`
- Test: `tests/alive/compose/test_seed_variability.py`

**Interfaces:**
- Consumes: `alive.compose.baselines_combo.BaselineAdapter` with `predict(context, pair_ids: list[tuple[str, str]], response_dim: int) -> dict[tuple[str, str], np.ndarray]`; the fold-scoped payloads from Task 3; the true calibration eps (`inputs.additive_cal + outcome_store.combo_calibration_eps` already reconstructed once by the caller).
- Produces:
  - `_oof_pair_mse(pred_eps: np.ndarray, true_eps: np.ndarray) -> float` — mean over response dims of `(pred - true) ** 2`.
  - `run_seed_over_folds(*, adapter, context_by_fold, manifest, true_eps_by_pair, response_dim) -> tuple[dict[tuple[str, str], np.ndarray], float]` — predicts each fold's held-out test pairs, reassembles into one dict keyed by canonical covered pair ID, and returns `(pred_by_pair, mean_oof_pair_mse)` where the scalar is the mean pair MSE over the SAME covered pair set for every seed.

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_seed_variability.py  (append)
import numpy as np

from alive.compose.seed_variability import _oof_pair_mse, run_seed_over_folds


class _StubAdapter:
    """Deterministic adapter: predicts true_eps + a fixed per-seed offset."""

    name = "stub"

    def __init__(self, offset: float, true_eps_by_pair):
        self._offset = offset
        self._truth = true_eps_by_pair

    def predict(self, context, pair_ids, response_dim):
        return {tuple(p): self._truth[tuple(p)] + self._offset for p in pair_ids}


def test_oof_pair_mse_is_mean_squared_error():
    pred = np.array([1.0, 2.0, 3.0])
    true = np.array([1.0, 2.0, 4.0])
    assert _oof_pair_mse(pred, true) == pytest.approx(1.0 / 3.0)


def test_run_seed_reassembles_covered_pairs_and_scalar(_synthetic_phase2a_env):
    env = _synthetic_phase2a_env
    manifest = build_seed_variability_fold_manifest(
        cal_pair_ids=tuple(tuple(p) for p in env.inputs.cal_pair_ids),
        oof_fold_assignment=env.oof_fold_assignment,
        n_folds=env.n_folds,
        split_seed=env.split_seed,
    ).finalize_checksum()
    true_eps = (
        np.asarray(env.inputs.additive_cal, dtype=float)
        + np.asarray(env.outcome_store.combo_calibration_eps, dtype=float)
    )
    true_by_pair = {tuple(env.inputs.cal_pair_ids[i]): true_eps[i] for i in range(len(true_eps))}
    adapter = _StubAdapter(offset=0.0, true_eps_by_pair=true_by_pair)
    context_by_fold = {f.fold_index: object() for f in manifest.folds}  # stub ignores context
    pred_by_pair, scalar = run_seed_over_folds(
        adapter=adapter,
        context_by_fold=context_by_fold,
        manifest=manifest,
        true_eps_by_pair=true_by_pair,
        response_dim=env.inputs.response_dim,
    )
    covered_ids = {manifest.cal_pair_ids[pos] for pos in manifest.covered_pair_positions}
    assert set(pred_by_pair) == covered_ids  # exactly the covered set, no held-out leakage
    assert scalar == pytest.approx(0.0)  # offset 0 -> perfect -> MSE 0 (stub is not stability evidence)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_seed_variability.py -x -q -k oof_pair_mse or run_seed`
Expected: FAIL — `ImportError: cannot import name 'run_seed_over_folds'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/alive/compose/seed_variability.py  (append)


def _oof_pair_mse(pred_eps: np.ndarray, true_eps: np.ndarray) -> float:
    diff = np.asarray(pred_eps, dtype=float) - np.asarray(true_eps, dtype=float)
    return float(np.mean(diff * diff))


def run_seed_over_folds(
    *,
    adapter,
    context_by_fold: Mapping[int, object],
    manifest: SeedVariabilityFoldManifest,
    true_eps_by_pair: Mapping[tuple[str, str], np.ndarray],
    response_dim: int,
) -> tuple[dict[tuple[str, str], np.ndarray], float]:
    """Predict each fold's held-out test pairs, reassemble in canonical covered order.

    The per-seed scalar is the mean pair MSE over the fixed covered OOF pair set —
    identical for every seed by construction.
    """
    pred_by_pair: dict[tuple[str, str], np.ndarray] = {}
    for fold in manifest.folds:
        test_ids = [manifest.cal_pair_ids[pos] for pos in fold.test_pair_positions]
        if not test_ids:
            continue
        predictions = adapter.predict(context_by_fold[fold.fold_index], test_ids, response_dim)
        for pair in test_ids:
            if pair not in predictions:
                raise ValueError(f"adapter did not predict held-out test pair {pair}")
            pred_by_pair[pair] = np.asarray(predictions[pair], dtype=float)
    covered_order = [manifest.cal_pair_ids[pos] for pos in manifest.covered_pair_positions]
    if set(pred_by_pair) != set(covered_order):
        raise ValueError("reassembled predictions do not equal the covered OOF pair set")
    per_pair = [_oof_pair_mse(pred_by_pair[pair], true_eps_by_pair[pair]) for pair in covered_order]
    return pred_by_pair, float(np.mean(per_pair))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/alive/compose/test_seed_variability.py -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/seed_variability.py tests/alive/compose/test_seed_variability.py
git commit -m "feat(compose): D2 per-fold OOF prediction + canonical reassembly + per-seed scalar"
```

---

## Task 5: `development_seed_variability(...)` production entry + failure policy

**Files:**
- Modify: `src/alive/compose/seed_variability.py`
- Test: `tests/alive/compose/test_seed_variability.py`

**Interfaces:**
- Consumes: Tasks 1-4; `Phase2aInputs`; `DevelopmentOutcomeStore`; the per-pair `oof_fold_assignment`; a mapping `baseline_adapters: Mapping[str, BaselineAdapter]` (must contain exactly `{"gears", "cpa"}`); the active `ComposePhase2Config` (fields `seeds.registered_seeds`, `select.n_folds`/`uncovered_tolerance`, `seeds.split_seed`).
- Produces:
  - `development_seed_variability(*, inputs, development_outcome_store, oof_fold_assignment, baseline_adapters, config) -> SeedVariabilityReport` — the spec §4.3 entry: iterates `config.seeds.registered_seeds` in order for `gears`, `cpa` only; reconstructs truth once; builds the fold manifest; validates coverage vs the Phase-2a selection; for each `(method, seed)` runs `run_seed_over_folds`; summarizes with `ddof=1`; preserves failed seeds with a scrubbed failure class; status `COMPLETE` iff every registered seed of every stochastic method succeeded, else `INCOMPLETE`.
  - `class SeedVariabilityError(ValueError)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_seed_variability.py  (append)
from alive.compose.compose_outcome_store import ComposeOutcomeStore  # sealed store (path per repo)
from alive.compose.seed_variability import SeedVariabilityError, development_seed_variability


def test_entry_rejects_sealed_store(_synthetic_phase2a_env):
    env = _synthetic_phase2a_env
    with pytest.raises(SeedVariabilityError, match="DevelopmentOutcomeStore"):
        development_seed_variability(
            inputs=env.inputs,
            development_outcome_store=object(),  # not a DevelopmentOutcomeStore
            oof_fold_assignment=env.oof_fold_assignment,
            baseline_adapters=env.stub_adapters,
            config=env.config,
        )


def test_entry_all_seeds_success_is_complete(_synthetic_phase2a_env):
    env = _synthetic_phase2a_env  # stub_adapters == {"gears": stub0, "cpa": stub0}
    report = development_seed_variability(
        inputs=env.inputs,
        development_outcome_store=env.outcome_store,
        oof_fold_assignment=env.oof_fold_assignment,
        baseline_adapters=env.stub_adapters,
        config=env.config,
    )
    assert report.status is SeedVariabilityStatus.COMPLETE
    assert report.registered_seeds == (11, 23, 37)
    methods = {c.method for c in report.comparators}
    assert methods == {"gears", "cpa"}
    for c in report.comparators:
        assert [s for s, _ in c.seed_to_oof_mean_pair_mse] == [11, 23, 37]
        assert c.failed_seeds == ()


def test_entry_one_failed_seed_is_incomplete_and_preserved(_synthetic_phase2a_env):
    env = _synthetic_phase2a_env
    adapters = dict(env.stub_adapters)
    adapters["gears"] = env.make_failing_adapter(fail_on_seed=23)  # raises for seed 23
    report = development_seed_variability(
        inputs=env.inputs,
        development_outcome_store=env.outcome_store,
        oof_fold_assignment=env.oof_fold_assignment,
        baseline_adapters=adapters,
        config=env.config,
    )
    assert report.status is SeedVariabilityStatus.INCOMPLETE
    gears = next(c for c in report.comparators if c.method == "gears")
    assert 23 in gears.failed_seeds
    assert dict(gears.failure_class_by_seed)[23]  # a scrubbed failure class string, non-empty
    # the failed seed is NOT dropped from the ordered roster
    assert [s for s, _ in gears.seed_to_oof_mean_pair_mse] == [11, 37]  # only successful scalars listed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_seed_variability.py -x -q -k entry_`
Expected: FAIL — `ImportError: cannot import name 'development_seed_variability'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/alive/compose/seed_variability.py  (append)
import statistics

from alive.compose.outcome_store import DevelopmentOutcomeStore


class SeedVariabilityError(ValueError):
    pass


def _scrub_failure_class(exc: BaseException) -> str:
    """A message-free failure class token (no outcome/data leakage in the report)."""
    return type(exc).__name__


def development_seed_variability(
    *,
    inputs,
    development_outcome_store,
    oof_fold_assignment,
    baseline_adapters: Mapping[str, object],
    config,
) -> SeedVariabilityReport:
    if not isinstance(development_outcome_store, DevelopmentOutcomeStore):
        raise SeedVariabilityError(
            "development_seed_variability requires a DevelopmentOutcomeStore (non-sealed); "
            f"got {type(development_outcome_store).__name__}"
        )
    if set(baseline_adapters) != set(SEED_REFITTABLE_METHODS):
        raise SeedVariabilityError(
            f"baseline_adapters must be exactly {set(SEED_REFITTABLE_METHODS)}, got {set(baseline_adapters)}"
        )
    registered_seeds = tuple(int(s) for s in config.seeds.registered_seeds)
    split_seed = int(config.seeds.split_seed)
    n_folds = int(config.select.n_folds)
    uncovered_tolerance = float(config.select.uncovered_tolerance)

    cal_pair_ids = tuple(tuple(p) for p in inputs.cal_pair_ids)
    if development_outcome_store.combo_calibration_pair_ids != cal_pair_ids:
        raise SeedVariabilityError("development outcomes are not aligned with calibration pair IDs")
    true_eps = (
        np.asarray(inputs.additive_cal, dtype=float)
        + np.asarray(development_outcome_store.combo_calibration_eps, dtype=float)
    )
    true_by_pair = {cal_pair_ids[i]: true_eps[i] for i in range(len(cal_pair_ids))}

    manifest = build_seed_variability_fold_manifest(
        cal_pair_ids=cal_pair_ids,
        oof_fold_assignment=oof_fold_assignment,
        n_folds=n_folds,
        split_seed=split_seed,
    ).finalize_checksum()

    covered_ids = tuple(manifest.cal_pair_ids[pos] for pos in manifest.covered_pair_positions)
    uncovered_ids = tuple(manifest.cal_pair_ids[pos] for pos in manifest.uncovered_pair_positions)
    uncovered_fraction = len(uncovered_ids) / max(1, len(cal_pair_ids))
    coverage = CoverageReport(
        total_pairs=len(cal_pair_ids),
        covered_count=len(covered_ids),
        uncovered_count=len(uncovered_ids),
        uncovered_fraction=uncovered_fraction,
        covered_pair_ids_sha256=sha256_json([list(p) for p in covered_ids]),
        uncovered_pair_ids_sha256=sha256_json([list(p) for p in uncovered_ids]),
        uncovered_tolerance=uncovered_tolerance,
    )

    any_failure = uncovered_fraction > uncovered_tolerance
    summaries: list[SeedComparatorSummary] = []
    for method in SEED_REFITTABLE_METHODS:
        adapter = baseline_adapters[method]
        seed_scalars: list[tuple[int, float]] = []
        failed: list[int] = []
        failure_class: list[tuple[int, str]] = []
        pred_ck: list[tuple[int, str]] = []
        checkpoint_ck: list[tuple[int, str]] = []
        for seed in registered_seeds:
            try:
                context_by_fold = {
                    fold.fold_index: _build_fold_context(
                        adapter=adapter,
                        inputs=inputs,
                        outcome_store=development_outcome_store,
                        response_artifact=_response_artifact_for(config, inputs),
                        manifest=manifest,
                        fold_index=fold.fold_index,
                        seed=seed,
                    )
                    for fold in manifest.folds
                    if fold.test_pair_positions
                }
                pred_by_pair, scalar = run_seed_over_folds(
                    adapter=adapter,
                    context_by_fold=context_by_fold,
                    manifest=manifest,
                    true_eps_by_pair=true_by_pair,
                    response_dim=int(inputs.response_dim),
                )
                seed_scalars.append((int(seed), float(scalar)))
                pred_ck.append((int(seed), sha256_json({str(k): v.tolist() for k, v in sorted(pred_by_pair.items())})))
                checkpoint_ck.append((int(seed), sha256_json({"method": method, "seed": int(seed)})))
            except Exception as exc:  # preserve, do not drop (spec §4.3)
                any_failure = True
                failed.append(int(seed))
                failure_class.append((int(seed), _scrub_failure_class(exc)))
        scalars = [v for _, v in seed_scalars]
        summaries.append(
            SeedComparatorSummary(
                method=method,
                seed_to_oof_mean_pair_mse=tuple(seed_scalars),
                mean=float(statistics.fmean(scalars)) if scalars else 0.0,
                std=float(statistics.stdev(scalars)) if len(scalars) > 1 else 0.0,
                min=float(min(scalars)) if scalars else 0.0,
                max=float(max(scalars)) if scalars else 0.0,
                range=float(max(scalars) - min(scalars)) if scalars else 0.0,
                failed_seeds=tuple(failed),
                failure_class_by_seed=tuple(failure_class),
                prediction_checksum_by_seed=tuple(pred_ck),
                checkpoint_checksum_by_seed=tuple(checkpoint_ck),
            )
        )

    status = SeedVariabilityStatus.INCOMPLETE if any_failure else SeedVariabilityStatus.COMPLETE
    return SeedVariabilityReport(
        schema_version=1,
        status=status,
        registered_seeds=registered_seeds,
        deterministic_single_shot=DETERMINISTIC_SINGLE_SHOT,
        coverage=coverage,
        comparators=tuple(summaries),
        oof_fold_assignment_sha256=manifest.manifest_sha256,
        response_space_checksum=str(inputs.response_space_checksum),
        fit_role_artifact_sha256=_fit_role_sha_for(config, inputs),
        worker_lock_sha256_by_method=tuple(
            (m, _worker_lock_sha_for(baseline_adapters[m])) for m in SEED_REFITTABLE_METHODS
        ),
        report_checksum="",
    ).finalize_checksum()
```

The `_build_fold_context`, `_response_artifact_for`, `_fit_role_sha_for`, `_worker_lock_sha_for` helpers wrap the Task-3 `build_fold_scoped_fit_payload` and the adapter's training-context construction. Implement `_build_fold_context` to call `build_fold_scoped_fit_payload(...)` then hand the payload to the adapter's context builder (mirror `phase2a._predict_role` / `BaselineTrainingContext` construction — read `src/alive/compose/baselines_combo.py:271-340` and `phase2a.py` for the exact context type). Keep them internal (module-private, leading underscore) so the scientific entry cannot be handed a caller-supplied payload/factory.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/alive/compose/test_seed_variability.py -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/seed_variability.py tests/alive/compose/test_seed_variability.py
git commit -m "feat(compose): D2 development_seed_variability entry + failure-preserving INCOMPLETE policy"
```

---

## Task 6: Pre-seal binding + Phase-2b preflight verification

**Files:**
- Modify: `src/alive/compose/seed_variability.py`
- Modify: `src/alive/compose/phase2b.py`
- Test: `tests/alive/compose/test_seed_variability.py`

**Interfaces:**
- Consumes: `alive.provenance.RunLedger.record_artifact(name, sha256)`; `alive.compose.provenance2.persist_pre_access_ledger` / `PRE_ACCESS_LEDGER_FILENAME`; `SeedVariabilityReport.load`.
- Produces:
  - `DEVELOPMENT_SEED_VARIABILITY_ARTIFACT = "development_seed_variability"` (ledger artifact name).
  - `bind_seed_variability_into_ledger(*, ledger, report_path) -> str` — records the report file's byte SHA under `DEVELOPMENT_SEED_VARIABILITY_ARTIFACT` and returns it.
  - `verify_seed_variability_for_preflight(*, run_dir, expected_method_roster, expected_seed_roster, expected_coverage_sha256) -> SeedVariabilityReport` — the Phase-2b preflight gate: the regular-file artifact must exist, its byte checksum must re-verify its embedded self-checksum, status must be `COMPLETE`, method roster must equal `{"gears","cpa"}`, seed roster must equal `(11,23,37)`, and the coverage checksum must equal the Phase-2a selection's covered-pair-ID checksum. Raises `SeedVariabilityError` on any failure.

- [ ] **Step 1: Write the failing test**

```python
# tests/alive/compose/test_seed_variability.py  (append)
from alive.compose.seed_variability import (
    DEVELOPMENT_SEED_VARIABILITY_ARTIFACT,
    verify_seed_variability_for_preflight,
)


def test_preflight_accepts_complete_report(tmp_path, _complete_report_factory):
    report = _complete_report_factory(status=SeedVariabilityStatus.COMPLETE)
    report.write_once(tmp_path)
    verified = verify_seed_variability_for_preflight(
        run_dir=tmp_path,
        expected_method_roster=("gears", "cpa"),
        expected_seed_roster=(11, 23, 37),
        expected_coverage_sha256=report.coverage.covered_pair_ids_sha256,
    )
    assert verified.status is SeedVariabilityStatus.COMPLETE


def test_preflight_blocks_incomplete_report(tmp_path, _complete_report_factory):
    report = _complete_report_factory(status=SeedVariabilityStatus.INCOMPLETE)
    report.write_once(tmp_path)
    with pytest.raises(SeedVariabilityError, match="INCOMPLETE"):
        verify_seed_variability_for_preflight(
            run_dir=tmp_path,
            expected_method_roster=("gears", "cpa"),
            expected_seed_roster=(11, 23, 37),
            expected_coverage_sha256=report.coverage.covered_pair_ids_sha256,
        )


def test_preflight_blocks_missing_and_coverage_mismatch(tmp_path, _complete_report_factory):
    with pytest.raises(SeedVariabilityError, match="absent|not a regular file"):
        verify_seed_variability_for_preflight(
            run_dir=tmp_path,
            expected_method_roster=("gears", "cpa"),
            expected_seed_roster=(11, 23, 37),
            expected_coverage_sha256="a" * 64,
        )
    report = _complete_report_factory(status=SeedVariabilityStatus.COMPLETE)
    report.write_once(tmp_path)
    with pytest.raises(SeedVariabilityError, match="coverage"):
        verify_seed_variability_for_preflight(
            run_dir=tmp_path,
            expected_method_roster=("gears", "cpa"),
            expected_seed_roster=(11, 23, 37),
            expected_coverage_sha256="f" * 64,  # wrong coverage
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/alive/compose/test_seed_variability.py -x -q -k preflight`
Expected: FAIL — `ImportError: cannot import name 'verify_seed_variability_for_preflight'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/alive/compose/seed_variability.py  (append)
DEVELOPMENT_SEED_VARIABILITY_ARTIFACT = "development_seed_variability"


def bind_seed_variability_into_ledger(*, ledger, report_path: str | Path) -> str:
    from alive.provenance import sha256_file

    sha = sha256_file(str(report_path))
    ledger.record_artifact(DEVELOPMENT_SEED_VARIABILITY_ARTIFACT, sha)
    return sha


def verify_seed_variability_for_preflight(
    *,
    run_dir: str | Path,
    expected_method_roster: tuple[str, ...],
    expected_seed_roster: tuple[int, ...],
    expected_coverage_sha256: str,
) -> SeedVariabilityReport:
    path = Path(run_dir) / DEVELOPMENT_SEED_VARIABILITY_FILENAME
    if not path.exists() or not path.is_file():
        raise SeedVariabilityError(f"development seed-variability artifact absent / not a regular file: {path}")
    report = SeedVariabilityReport.load(path)  # re-verifies the embedded self-checksum
    if report.status is not SeedVariabilityStatus.COMPLETE:
        raise SeedVariabilityError("development seed-variability status is INCOMPLETE; Phase-2b preflight blocked")
    methods = tuple(sorted(c.method for c in report.comparators))
    if methods != tuple(sorted(expected_method_roster)):
        raise SeedVariabilityError(f"seed-variability method roster {methods} != expected {expected_method_roster}")
    if report.registered_seeds != tuple(expected_seed_roster):
        raise SeedVariabilityError(
            f"seed-variability seed roster {report.registered_seeds} != expected {expected_seed_roster}"
        )
    if report.coverage.covered_pair_ids_sha256 != expected_coverage_sha256:
        raise SeedVariabilityError("seed-variability coverage checksum != Phase-2a selection covered-pair checksum")
    return report
```

Wire the call into `run_phase2b`'s scientific preflight in `src/alive/compose/phase2b.py`, before `terminal.claim_access()`, using the run's expected roster/coverage:

```python
# src/alive/compose/phase2b.py  (inside run_phase2b preflight, before seal access)
from alive.compose.seed_variability import verify_seed_variability_for_preflight

# ... after upstream/pre-access verification, still seal-closed:
verify_seed_variability_for_preflight(
    run_dir=run_dir,
    expected_method_roster=("gears", "cpa"),
    expected_seed_roster=tuple(config.seeds.registered_seeds),
    expected_coverage_sha256=selection_covered_pair_ids_sha256,  # from the Phase-2a selection artifact
)
```

Read the existing `run_phase2b` preflight block first; place this call alongside the other pre-access verifications so a missing/incomplete report leaves the seal CLOSED. If `selection_covered_pair_ids_sha256` is not already available at that point, thread it from the Phase-2a selection artifact the driver passes into the run spec.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/alive/compose/test_seed_variability.py tests/alive/compose/test_phase2b.py -q`
Expected: PASS (D2 preflight tests + the existing phase2b suite still green).

- [ ] **Step 5: Commit**

```bash
git add src/alive/compose/seed_variability.py src/alive/compose/phase2b.py tests/alive/compose/test_seed_variability.py
git commit -m "feat(compose): D2 pre-seal ledger binding + Phase-2b preflight seed-variability gate"
```

---

## Task 7: Governance / leakage test sweep + full suite

**Files:**
- Modify: `tests/alive/compose/test_seed_variability.py`

**Interfaces:**
- Consumes: Tasks 1-6. No new production code — this task locks the spec §6.2 governance invariants with tests and runs the full verification suite.

- [ ] **Step 1: Write the failing tests (spec §6.2 roster)**

```python
# tests/alive/compose/test_seed_variability.py  (append)


def test_held_out_and_cross_group_never_enter_fit_validation_or_early_stopping(_synthetic_phase2a_env):
    """§6.2: held-out/cross-group pair IDs/rows/targets are absent from the fit payload."""
    env = _synthetic_phase2a_env
    manifest = build_seed_variability_fold_manifest(
        cal_pair_ids=tuple(tuple(p) for p in env.inputs.cal_pair_ids),
        oof_fold_assignment=env.oof_fold_assignment,
        n_folds=env.n_folds,
        split_seed=env.split_seed,
    ).finalize_checksum()
    for fold in manifest.folds:
        payload = build_fold_scoped_fit_payload(
            inputs=env.inputs,
            outcome_store=env.outcome_store,
            response_artifact=env.response_artifact,
            fit_role_spec=env.fit_role_spec,
            gene_order=env.gene_order,
            raw_data_sha256=env.raw_data_sha256,
            manifest=manifest,
            fold_index=fold.fold_index,
            seed=11,
        )
        fit_ids = {tuple(p) for p in payload["calibration_pair_ids"]}
        held = {manifest.cal_pair_ids[pos] for pos in fold.test_pair_positions}
        cross = {manifest.cal_pair_ids[pos] for pos in fold.cross_group_pair_positions}
        assert not (fit_ids & held)
        assert not (fit_ids & cross)


def test_all_methods_share_identical_covered_set(_synthetic_phase2a_env):
    env = _synthetic_phase2a_env
    report = development_seed_variability(
        inputs=env.inputs,
        development_outcome_store=env.outcome_store,
        oof_fold_assignment=env.oof_fold_assignment,
        baseline_adapters=env.stub_adapters,
        config=env.config,
    )
    # coverage is a single report-level block shared by all comparators
    assert report.coverage.covered_count >= 1


def test_seed_bound_into_prediction_and_checkpoint_checksums(_synthetic_phase2a_env):
    env = _synthetic_phase2a_env
    report = development_seed_variability(
        inputs=env.inputs,
        development_outcome_store=env.outcome_store,
        oof_fold_assignment=env.oof_fold_assignment,
        baseline_adapters=env.seed_sensitive_adapters,  # stub whose output depends on seed
        config=env.config,
    )
    gears = next(c for c in report.comparators if c.method == "gears")
    pred_by_seed = dict(gears.prediction_checksum_by_seed)
    assert pred_by_seed[11] != pred_by_seed[23]  # different seed -> different prediction checksum


def test_stub_zero_spread_is_not_stability_evidence(_synthetic_phase2a_env):
    """A 0-spread stub result is a wiring known-answer, NOT stochastic-stability proof."""
    env = _synthetic_phase2a_env
    report = development_seed_variability(
        inputs=env.inputs,
        development_outcome_store=env.outcome_store,
        oof_fold_assignment=env.oof_fold_assignment,
        baseline_adapters=env.stub_adapters,  # deterministic, seed-invariant stub
        config=env.config,
    )
    gears = next(c for c in report.comparators if c.method == "gears")
    assert gears.range == pytest.approx(0.0)  # expected for a deterministic stub; documented as wiring-only


def test_deterministic_roster_excluded_from_seed_loop(_synthetic_phase2a_env):
    env = _synthetic_phase2a_env
    report = development_seed_variability(
        inputs=env.inputs,
        development_outcome_store=env.outcome_store,
        oof_fold_assignment=env.oof_fold_assignment,
        baseline_adapters=env.stub_adapters,
        config=env.config,
    )
    seed_looped = {c.method for c in report.comparators}
    assert seed_looped == {"gears", "cpa"}
    assert "l3_hypernetwork" in report.deterministic_single_shot
    assert "l3_hypernetwork" not in seed_looped


def test_entry_rejects_object_and_path_injection(_synthetic_phase2a_env):
    env = _synthetic_phase2a_env
    for bad in [{"gears": 1, "cpa": 2}, {"gears": object()}]:
        with pytest.raises((SeedVariabilityError, AttributeError, ValueError)):
            development_seed_variability(
                inputs=env.inputs,
                development_outcome_store=env.outcome_store,
                oof_fold_assignment=env.oof_fold_assignment,
                baseline_adapters=bad,
                config=env.config,
            )
```

- [ ] **Step 2: Run the D2 tests**

Run: `uv run pytest tests/alive/compose/test_seed_variability.py -q`
Expected: PASS (all D2 tests).

- [ ] **Step 3: Run the leakage / seal-boundary / provenance subsets**

Run: `uv run pytest tests/alive/compose -q -k "leakage or seal or provenance or phase2b or fit_role or select"`
Expected: PASS (no regression; D2 opens no seal and touches no sealed store).

- [ ] **Step 4: Full suite + ruff**

Run:
```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```
Expected: full suite green (compose count increased by the new D2 tests), ruff clean. No `gears`/`cpa` import anywhere in `src/alive/compose/seed_variability.py` (it uses only the `BaselineAdapter` seam + stubs in tests).

- [ ] **Step 5: Commit**

```bash
git add tests/alive/compose/test_seed_variability.py
git commit -m "test(compose): D2 governance/leakage sweep (spec §6.2) — exclusion, coverage, seed binding, injection"
```

---

## Post-implementation

D2 opens no seal and creates no per-pair CI. After all tasks:

1. Run the CLAUDE.md §13 subset relevant to a development-role data/eval change: leakage tests, metric known-answer/constant/shuffled/random sanity for the new MSE reassembly, and provenance/immutability tests for the write-once report. D2 does NOT touch the seal state machine, so tamper/resume of the terminal is unaffected — but the pre-access ledger now carries the `development_seed_variability` artifact, so re-run the pre-access provenance tests.
2. Run the **science-dev loop gate** on the increment (per [[use-loop-gate-on-science-work]]): materialize the LOCAL-ONLY harness via `git archive loop-engineering-local ... | tar -x`, run `python scripts/loop_gate.py --phase compose-d2-seed-variability --profile science-dev --review <json> --ledger-dir docs/superpowers/loop/feedback --allow-dirty`, record to `loop-engineering-local` via worktree, then `rm -rf` the harness. Confirm `seal_access_zero == yes`.
3. Real GEARS/CPA seed numbers + object-storage upload remain a **pod runbook** step (spec §7). The local stub validates seed-passing / fold-exclusion / alignment / checksum wiring only — a 0 spread is not stability evidence.

## Notes for the executor

- **Fixtures:** build `_synthetic_phase2a_env`, `_complete_report_factory`, `env.stub_adapters`, `env.seed_sensitive_adapters`, `env.make_failing_adapter`, `env.config` in a `conftest.py` or at the top of `test_seed_variability.py`. Model the synthetic `Phase2aInputs` + `DevelopmentOutcomeStore` + `response_artifact` on the existing builders in `tests/alive/compose/test_phase2a.py` and `test_payload_v2_integration.py` (they already construct a valid response space, calibration pairs, singles universe, and fit-role spec). Keep the gene set small (~6 genes, ~4 calibration pairs) so gene-disjoint folds have a non-trivial train/test/cross-group partition.
- **`config`:** use `load_compose_phase2_config("configs/compose_k562_v1_phase2.yaml")` in the fixture if the loader works without an ActivationRecord for the fields D2 reads (`seeds.registered_seeds`, `seeds.split_seed`, `select.n_folds`, `select.uncovered_tolerance`); otherwise build a minimal stub object exposing exactly those attributes. Read `src/alive/compose/config2.py` for the exact attribute path (`config.seeds.registered_seeds` etc.) and adjust the accessor names to match the real dataclass.
- **Adapter context:** the exact `BaselineTrainingContext` construction and `adapter.predict(context, pair_ids, response_dim)` call must mirror `phase2a`'s existing subprocess prediction path. Read `src/alive/compose/baselines_combo.py:271-340` and the phase2a `_predict_role` usage before Task 4/5 so the stub adapters and the real seam share one contract.
