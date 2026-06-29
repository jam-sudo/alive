"""Tests for src/alive/data/outcome_store.py — structurally sealed outcome store.

TDD order: tests written first; the implementation must pass all of them.

All tests use small synthetic AnnData fixtures; the real .h5ad is NOT required.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anndata
import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

from alive.config import SplitFractions
from alive.data.manifest import build_manifest_from_index
from alive.data.outcome_store import (
    OutcomeStore,
    Population,
    ReplogleOutcomeStore,
    SealingError,
)
from alive.data.replogle import DatasetSchema, build_index

# ---------------------------------------------------------------------------
# Constants & helpers
# ---------------------------------------------------------------------------

_PERT_KEY = "target"
_CTRL_VAL = "ctrl"
_GENE_IDS = ["g0", "g1", "g2", "g3", "g4"]
_N_GENES = len(_GENE_IDS)

# Fractions: ensure a nonzero sealed_evaluation portion
_FRACTIONS = SplitFractions(
    base_train=0.40,
    method_development=0.25,
    conformal_calibration=0.15,
    sealed_evaluation=0.20,
)
_SEED = 7


def _make_adata(
    *,
    n_ctrl: int = 40,
    pert_cells: dict[str, int] | None = None,
) -> anndata.AnnData:
    """Build a minimal synthetic AnnData for outcome-store tests."""
    if pert_cells is None:
        # 8 perturbations × 20 cells each = 160 perturbed cells
        pert_cells = {f"gene{i}": 20 for i in range(8)}

    labels: list[str] = [_CTRL_VAL] * n_ctrl
    for label, n in pert_cells.items():
        labels.extend([label] * n)

    n_cells = len(labels)
    X = sp.random(n_cells, _N_GENES, density=0.5, format="csr", dtype=np.float32)
    X.data[:] = 1.0
    obs = pd.DataFrame({_PERT_KEY: labels}, index=[f"c{i}" for i in range(n_cells)])
    var = pd.DataFrame(index=_GENE_IDS)
    return anndata.AnnData(X=X, obs=obs, var=var)


def _build_store(
    adata: anndata.AnnData,
    tmp_path: Path,
) -> tuple[ReplogleOutcomeStore, list[str], list[str]]:
    """
    Build a ReplogleOutcomeStore from synthetic AnnData.

    Returns (store, unsealed_ids, sealed_ids).
    """
    schema = DatasetSchema(perturbation_key=_PERT_KEY, control_value=_CTRL_VAL)
    index = build_index(adata, schema, min_cells=5)
    manifest = build_manifest_from_index(index, _FRACTIONS, _SEED)

    sealed_ids = list(manifest.ids_for("sealed_evaluation"))
    all_ids = list(index.eligible_perturbations)
    unsealed_ids = [i for i in all_ids if i not in sealed_ids]

    audit_path = tmp_path / "audit.jsonl"
    store = ReplogleOutcomeStore(
        index=index,
        source=adata,
        manifest=manifest,
        audit_path=audit_path,
    )
    return store, unsealed_ids, sealed_ids


# ---------------------------------------------------------------------------
# Spy / double for leakage guard
# ---------------------------------------------------------------------------


class SpyOutcomeStore:
    """Test double that records all ids seen by each method."""

    def __init__(self) -> None:
        self._unsealed_ids: list[str] = []
        self._evaluate_calls: list[tuple[str, list[str]]] = []

    def read_unsealed(self, perturbation_ids: Sequence[str]) -> dict[str, Population]:
        self._unsealed_ids.extend(perturbation_ids)
        return {}

    def evaluate_sealed_once(
        self, run_id: str, perturbation_ids: Sequence[str]
    ) -> dict[str, Population]:
        self._evaluate_calls.append((run_id, list(perturbation_ids)))
        return {}


def _fitting_function_that_reads_only_unsealed(store: OutcomeStore, ids: Sequence[str]) -> None:
    """Simulate a fitting routine that must ONLY call read_unsealed."""
    _ = store.read_unsealed(ids)


# ---------------------------------------------------------------------------
# 1. Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    def test_concrete_store_satisfies_protocol(self, tmp_path: Path) -> None:
        adata = _make_adata()
        store, _, _ = _build_store(adata, tmp_path)
        assert isinstance(store, OutcomeStore)

    def test_spy_satisfies_protocol(self) -> None:
        assert isinstance(SpyOutcomeStore(), OutcomeStore)


# ---------------------------------------------------------------------------
# 2. Unsealed reads work for non-sealed ids
# ---------------------------------------------------------------------------


class TestUnsealedReads:
    def test_returns_correct_populations(self, tmp_path: Path) -> None:
        adata = _make_adata()
        schema = DatasetSchema(perturbation_key=_PERT_KEY, control_value=_CTRL_VAL)
        index = build_index(adata, schema, min_cells=5)
        manifest = build_manifest_from_index(index, _FRACTIONS, _SEED)

        sealed_ids = set(manifest.ids_for("sealed_evaluation"))
        unsealed_ids = [i for i in index.eligible_perturbations if i not in sealed_ids]
        assert len(unsealed_ids) >= 2, "fixture must have at least 2 unsealed ids"

        store = ReplogleOutcomeStore(
            index=index,
            source=adata,
            manifest=manifest,
            audit_path=tmp_path / "audit.jsonl",
        )

        result = store.read_unsealed(unsealed_ids[:2])
        assert len(result) == 2

        for pid in unsealed_ids[:2]:
            assert pid in result
            pop = result[pid]
            assert isinstance(pop, Population)
            assert pop.perturbation_id == pid
            # Shape: (n_cells_for_pert, n_genes)
            expected_n_cells = len(index.cell_indices(pid))
            assert pop.cells.shape == (expected_n_cells, _N_GENES)
            assert isinstance(pop.cells, np.ndarray)

    def test_population_contains_correct_gene_axis(self, tmp_path: Path) -> None:
        adata = _make_adata()
        store, unsealed_ids, _ = _build_store(adata, tmp_path)
        result = store.read_unsealed([unsealed_ids[0]])
        pop = result[unsealed_ids[0]]
        assert pop.cells.shape[1] == _N_GENES


# ---------------------------------------------------------------------------
# 3. Sealed ids are denied via the ordinary read path
# ---------------------------------------------------------------------------


class TestSealedReadDenied:
    def test_sealed_id_raises_sealing_error(self, tmp_path: Path) -> None:
        adata = _make_adata()
        store, _, sealed_ids = _build_store(adata, tmp_path)
        assert len(sealed_ids) >= 1, "fixture must produce at least 1 sealed id"

        with pytest.raises(SealingError, match=sealed_ids[0]):
            store.read_unsealed([sealed_ids[0]])

    def test_mixed_request_is_fail_closed(self, tmp_path: Path) -> None:
        """A mixed [unsealed, sealed] request raises and returns NOTHING."""
        adata = _make_adata()
        store, unsealed_ids, sealed_ids = _build_store(adata, tmp_path)
        assert unsealed_ids and sealed_ids

        with pytest.raises(SealingError):
            store.read_unsealed([unsealed_ids[0], sealed_ids[0]])

        # The call must not have returned a partial dict — ensure the raise
        # propagated before any data was handed back.  We verify by checking
        # that the call raised (the with-block above already asserts this) and
        # that no returned value was captured (implicit from the raise).

    def test_mixed_request_unsealed_id_not_leaked(self, tmp_path: Path) -> None:
        """After a mixed-request SealingError, the unsealed id's data is not returned."""
        adata = _make_adata()
        store, unsealed_ids, sealed_ids = _build_store(adata, tmp_path)

        returned: dict | None = None
        try:
            returned = store.read_unsealed([unsealed_ids[0], sealed_ids[0]])
        except SealingError:
            pass

        assert returned is None, "read_unsealed must not return a partial dict on SealingError"

    def test_unknown_id_raises_sealing_error(self, tmp_path: Path) -> None:
        adata = _make_adata()
        store, _, _ = _build_store(adata, tmp_path)

        with pytest.raises(SealingError, match="unknown_id_xyz"):
            store.read_unsealed(["unknown_id_xyz"])


# ---------------------------------------------------------------------------
# 4. evaluate_sealed_once works once and logs the audit record
# ---------------------------------------------------------------------------


class TestEvaluateSealedOnce:
    def test_returns_sealed_populations(self, tmp_path: Path) -> None:
        adata = _make_adata()
        store, _, sealed_ids = _build_store(adata, tmp_path)
        assert sealed_ids

        result = store.evaluate_sealed_once("run-001", sealed_ids)
        assert set(result.keys()) == set(sealed_ids)

        for pid, pop in result.items():
            assert isinstance(pop, Population)
            assert pop.perturbation_id == pid
            schema = DatasetSchema(perturbation_key=_PERT_KEY, control_value=_CTRL_VAL)
            index = build_index(adata, schema, min_cells=5)
            expected_n_cells = len(index.cell_indices(pid))
            assert pop.cells.shape == (expected_n_cells, _N_GENES)

    def test_audit_count_is_one_after_first_access(self, tmp_path: Path) -> None:
        adata = _make_adata()
        store, _, sealed_ids = _build_store(adata, tmp_path)

        store.evaluate_sealed_once("run-001", sealed_ids)
        assert store.sealed_access_count == 1

    def test_audit_file_exists_and_contains_run_id(self, tmp_path: Path) -> None:
        adata = _make_adata()
        audit_path = tmp_path / "audit.jsonl"
        schema = DatasetSchema(perturbation_key=_PERT_KEY, control_value=_CTRL_VAL)
        index = build_index(adata, schema, min_cells=5)
        manifest = build_manifest_from_index(index, _FRACTIONS, _SEED)
        sealed_ids = list(manifest.ids_for("sealed_evaluation"))
        store = ReplogleOutcomeStore(
            index=index, source=adata, manifest=manifest, audit_path=audit_path
        )

        store.evaluate_sealed_once("run-abc", sealed_ids)

        assert audit_path.exists()
        lines = [ln for ln in audit_path.read_text().splitlines() if ln.strip()]
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["run_id"] == "run-abc"
        assert sorted(record["perturbation_ids"]) == sorted(sealed_ids)
        assert record["count"] == len(sealed_ids)
        assert "content_hash" in record


# ---------------------------------------------------------------------------
# 5. Second sealed access fails (same run_id)
# ---------------------------------------------------------------------------


class TestOnceOnlyEnforcement:
    def test_concurrent_claim_has_exactly_one_winner(self, tmp_path: Path, monkeypatch) -> None:
        """Two stores on one audit_path racing distinct run_ids past the audit
        check: the write-once audit (O_EXCL link) admits exactly one winner."""
        adata = _make_adata()
        schema = DatasetSchema(perturbation_key=_PERT_KEY, control_value=_CTRL_VAL)
        index = build_index(adata, schema, min_cells=5)
        manifest = build_manifest_from_index(index, _FRACTIONS, _SEED)
        sealed_ids = list(manifest.ids_for("sealed_evaluation"))
        audit_path = tmp_path / "audit.jsonl"
        stores = [
            ReplogleOutcomeStore(
                index=index, source=adata, manifest=manifest, audit_path=audit_path
            )
            for _ in range(2)
        ]
        barrier = threading.Barrier(2)
        original = ReplogleOutcomeStore._assert_not_previously_accessed

        def synchronized_check(store, run_id):
            # Force both threads past the (empty) audit check before either writes.
            original(store, run_id)
            barrier.wait()

        monkeypatch.setattr(
            ReplogleOutcomeStore,
            "_assert_not_previously_accessed",
            synchronized_check,
        )

        def attempt(item):
            run_id, store = item
            try:
                store.evaluate_sealed_once(run_id, sealed_ids)
                return "success"
            except SealingError:
                return "refused"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, [("run-a", stores[0]), ("run-b", stores[1])]))
        assert sorted(results) == ["refused", "success"]
        assert len(audit_path.read_text(encoding="utf-8").splitlines()) == 1

    def test_second_call_same_run_id_raises(self, tmp_path: Path) -> None:
        adata = _make_adata()
        store, _, sealed_ids = _build_store(adata, tmp_path)

        store.evaluate_sealed_once("run-001", sealed_ids)

        with pytest.raises(SealingError, match="run-001"):
            store.evaluate_sealed_once("run-001", sealed_ids)

    def test_second_call_fresh_store_same_audit_path_raises(self, tmp_path: Path) -> None:
        """Simulate a new process by creating a fresh ReplogleOutcomeStore instance
        pointed at the same audit_path.  The once-only guarantee must hold."""
        adata = _make_adata()
        schema = DatasetSchema(perturbation_key=_PERT_KEY, control_value=_CTRL_VAL)
        index = build_index(adata, schema, min_cells=5)
        manifest = build_manifest_from_index(index, _FRACTIONS, _SEED)
        sealed_ids = list(manifest.ids_for("sealed_evaluation"))
        audit_path = tmp_path / "audit.jsonl"

        # First access with store_a
        store_a = ReplogleOutcomeStore(
            index=index, source=adata, manifest=manifest, audit_path=audit_path
        )
        store_a.evaluate_sealed_once("run-cross-process", sealed_ids)

        # "New process": fresh store_b pointed at same audit_path
        store_b = ReplogleOutcomeStore(
            index=index, source=adata, manifest=manifest, audit_path=audit_path
        )
        with pytest.raises(SealingError, match="run-cross-process"):
            store_b.evaluate_sealed_once("run-cross-process", sealed_ids)

    def test_different_run_id_is_refused_after_first(self, tmp_path: Path) -> None:
        """Only one run_id may ever open the sealed cohort per audit_path.
        A different run_id on the same audit_path must also be refused."""
        adata = _make_adata()
        store, _, sealed_ids = _build_store(adata, tmp_path)

        store.evaluate_sealed_once("run-first", sealed_ids)

        with pytest.raises(SealingError):
            store.evaluate_sealed_once("run-second", sealed_ids)


# ---------------------------------------------------------------------------
# 6. evaluate_sealed_once rejects non-sealed ids
# ---------------------------------------------------------------------------


class TestSealedMethodRejectsNonSealed:
    def test_unsealed_id_in_evaluate_raises(self, tmp_path: Path) -> None:
        adata = _make_adata()
        store, unsealed_ids, _ = _build_store(adata, tmp_path)
        assert unsealed_ids

        with pytest.raises(SealingError, match=unsealed_ids[0]):
            store.evaluate_sealed_once("run-bad", [unsealed_ids[0]])


# ---------------------------------------------------------------------------
# 7. Spy / leakage guard
# ---------------------------------------------------------------------------


class TestSpyLeakageGuard:
    def test_fitting_function_records_zero_sealed_ids(self) -> None:
        """A fitting routine using only read_unsealed must never touch sealed ids."""
        spy = SpyOutcomeStore()
        unsealed = ["gene0", "gene1", "gene2"]

        _fitting_function_that_reads_only_unsealed(spy, unsealed)

        assert spy._evaluate_calls == [], "evaluate_sealed_once must not be called during fitting"
        # None of the spy's unsealed reads should be sealed ids (in this spy there are none)
        assert "sealed_gene" not in spy._unsealed_ids

    def test_spy_records_unsealed_call(self) -> None:
        spy = SpyOutcomeStore()
        spy.read_unsealed(["geneA", "geneB"])
        assert spy._unsealed_ids == ["geneA", "geneB"]

    def test_spy_records_evaluate_call(self) -> None:
        spy = SpyOutcomeStore()
        spy.evaluate_sealed_once("run-x", ["sealed1", "sealed2"])
        assert len(spy._evaluate_calls) == 1
        run_id, ids = spy._evaluate_calls[0]
        assert run_id == "run-x"
        assert ids == ["sealed1", "sealed2"]


# ---------------------------------------------------------------------------
# 8. Controls
# ---------------------------------------------------------------------------


class TestControls:
    def test_read_controls_returns_control_population(self, tmp_path: Path) -> None:
        adata = _make_adata(n_ctrl=40)
        store, _, _ = _build_store(adata, tmp_path)

        ctrl_pop = store.read_controls()
        assert isinstance(ctrl_pop, Population)
        assert ctrl_pop.perturbation_id == _CTRL_VAL
        assert ctrl_pop.cells.shape == (40, _N_GENES)

    def test_read_unsealed_with_control_value_raises(self, tmp_path: Path) -> None:
        """Control value requested via read_unsealed must raise SealingError."""
        adata = _make_adata()
        store, _, _ = _build_store(adata, tmp_path)

        with pytest.raises(SealingError):
            store.read_unsealed([_CTRL_VAL])


# ---------------------------------------------------------------------------
# 9. Bounded materialization sentinel (I2: stateless — no module-level mutable)
# ---------------------------------------------------------------------------


def _make_no_global_toarray_csr(full_n_cells: int) -> type:
    """Return a CSR subclass that blocks densification of the full matrix.

    The sentinel is STATELESS: the full cell count is captured at construction
    time via a closure, so no module-level mutable global is needed and the
    class is safe to use in parallel test runs.

    ``toarray``/``todense`` raise only when called on a matrix whose row count
    equals *full_n_cells* (the original full matrix).  Sliced sub-matrices
    (fewer rows) are allowed — that is exactly the bounded per-population
    densify the store legitimately performs.
    """

    class _NoGlobalToarrayCSR(sp.csr_matrix):  # type: ignore[misc]
        """CSR matrix that refuses full-matrix densification."""

        def toarray(self, order=None, out=None):  # type: ignore[override]
            if self.shape[0] == full_n_cells:
                raise AssertionError(
                    "Global toarray() called on full matrix — bounded densify only!"
                )
            return super().toarray(order=order, out=out)

        def todense(self, order=None, out=None):  # type: ignore[override]
            if self.shape[0] == full_n_cells:
                raise AssertionError(
                    "Global todense() called on full matrix — bounded densify only!"
                )
            return super().todense(order=order, out=out)

    return _NoGlobalToarrayCSR


class TestBoundedMaterialization:
    def test_no_global_densify_on_unsealed_read(self, tmp_path: Path) -> None:
        n_ctrl = 40
        pert_cells = {f"gene{i}": 20 for i in range(8)}
        labels: list[str] = [_CTRL_VAL] * n_ctrl
        for label, n in pert_cells.items():
            labels.extend([label] * n)
        n_cells = len(labels)

        # I2 fix: sentinel class is constructed with the cell count in a closure;
        # no module-level mutable global.
        NoGlobalToarrayCSR = _make_no_global_toarray_csr(n_cells)

        X_inner = sp.random(n_cells, _N_GENES, density=0.5, format="csr", dtype=np.float32)
        X_inner.data[:] = 1.0
        X = NoGlobalToarrayCSR(X_inner)

        obs = pd.DataFrame({_PERT_KEY: labels}, index=[f"c{i}" for i in range(n_cells)])
        var = pd.DataFrame(index=_GENE_IDS)
        adata = anndata.AnnData(X=X, obs=obs, var=var)

        schema = DatasetSchema(perturbation_key=_PERT_KEY, control_value=_CTRL_VAL)
        index = build_index(adata, schema, min_cells=5)
        manifest = build_manifest_from_index(index, _FRACTIONS, _SEED)
        sealed_ids = list(manifest.ids_for("sealed_evaluation"))
        unsealed_ids = [i for i in index.eligible_perturbations if i not in sealed_ids]

        store = ReplogleOutcomeStore(
            index=index,
            source=adata,
            manifest=manifest,
            audit_path=tmp_path / "audit.jsonl",
        )

        # These must NOT trigger global toarray/todense
        _ = store.read_unsealed(unsealed_ids[:2])
        _ = store.read_controls()
        _ = store.evaluate_sealed_once("run-bounded", sealed_ids)


# ---------------------------------------------------------------------------
# 10. Fail-safe ordering: audit written BEFORE materialization (I1)
# ---------------------------------------------------------------------------


class TestFailSafeAuditOrdering:
    def test_failed_materialization_still_burns_run_id(self, tmp_path: Path) -> None:
        """A crash during _materialise_populations must still consume the run_id.

        The audit record is written BEFORE materialisation.  If materialisation
        then raises, the run_id is permanently burned: a subsequent call with
        the same run_id must raise SealingError and sealed_access_count == 1.
        """
        adata = _make_adata()
        store, _, sealed_ids = _build_store(adata, tmp_path)
        assert sealed_ids

        # Monkeypatch: make _materialise_populations raise after the audit write.
        original_materialise = store._materialise_populations

        def _failing_materialise(ids: list) -> dict:
            raise RuntimeError("simulated OOM during materialisation")

        store._materialise_populations = _failing_materialise  # type: ignore[method-assign]

        # The call must raise (from the injected failure).
        with pytest.raises(RuntimeError, match="simulated OOM"):
            store.evaluate_sealed_once("run-burned", sealed_ids)

        # (a) The audit record must have been written before the failure.
        assert store.sealed_access_count == 1, (
            "audit record must be written before materialisation so a crash still counts"
        )

        # Restore original materialise so we can test the re-access check.
        store._materialise_populations = original_materialise  # type: ignore[method-assign]

        # (b) A subsequent call with the same run_id must be refused — the seal is burned.
        with pytest.raises(SealingError):
            store.evaluate_sealed_once("run-burned", sealed_ids)
