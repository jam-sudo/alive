# tests/alive/compose/test_baseline_failclosed.py
"""SYNTHETIC-ONLY: fail-closed terminal state for an unavailable deep backend."""

from __future__ import annotations

import sys

import numpy as np
import pytest

from alive.compose.baseline_subprocess import SubprocessBaselineBackend
from alive.compose.baselines_combo import (
    BaselineAdapter,
    BaselineTrainingContext,
    BaselineUnavailable,
)
from alive.compose.freeze import REQUIRED_METHODS, FreezeError, _validate_role_predictions


def _context() -> BaselineTrainingContext:
    return BaselineTrainingContext(
        allowed_roles=frozenset({"singles", "combo_calibration"}),
        pair_manifest_checksum="d",
        response_space_checksum="c",
        training_pair_ids=(("B", "C"),),
        single_gene_ids=("A", "B", "C"),
    )


def test_unavailable_backend_raises_baseline_unavailable():
    be = SubprocessBaselineBackend(
        name="gears",
        env_python=sys.executable,
        worker_script="x",
        import_name="definitely_not_a_real_module_xyz",
    )
    adapter = BaselineAdapter(name="gears", backend=be)
    with pytest.raises(BaselineUnavailable):
        adapter.predict(_context(), [("A", "B")], 3)


def test_incomplete_roster_after_unavailable_backend_raises_freezeerror():
    # An unavailable deep backend (e.g. gears) contributes NO predictions; the
    # roster-completeness check must then raise FreezeError, never accept a
    # partial roster (the fail-closed terminal state — see spec-review med finding).
    pair = ("A", "B")  # canonical (min, max)
    vec = np.zeros(3)
    preds = {m: {pair: vec} for m in REQUIRED_METHODS if m != "gears"}
    with pytest.raises(FreezeError, match="missing"):
        _validate_role_predictions("sealed_double_unseen", REQUIRED_METHODS, (pair,), preds, 3)
