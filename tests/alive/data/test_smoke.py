"""Tests for the ESM real-forward smoke-test helpers (A100 prep, Gate C).

The pure pooling + verification logic is tested here WITHOUT torch; the actual
``Esm2Encoder`` forward is exercised by ``scripts/esm_smoke.py`` on the A100.
"""

from __future__ import annotations

import numpy as np
import pytest

from alive.data.smoke import SmokeReport, check_pooled, mean_pool


def test_mean_pool_collapses_residue_axis() -> None:
    # two sequences with different lengths, dim=4
    embs = [np.ones((3, 4), dtype=np.float32), np.full((5, 4), 2.0, dtype=np.float32)]
    pooled = mean_pool(embs)
    assert pooled.shape == (2, 4)
    assert np.allclose(pooled[0], 1.0)
    assert np.allclose(pooled[1], 2.0)


def test_check_pooled_passes_on_finite_correct_dim() -> None:
    pooled = np.random.default_rng(0).normal(size=(10, 1280)).astype(np.float32)
    rep = check_pooled(pooled, expected_dim=1280)
    assert isinstance(rep, SmokeReport)
    assert rep.n == 10
    assert rep.dim == 1280
    assert rep.dim_ok is True
    assert rep.all_finite is True
    assert rep.ok is True


def test_check_pooled_fails_on_wrong_dim() -> None:
    pooled = np.zeros((4, 320), dtype=np.float32)
    rep = check_pooled(pooled, expected_dim=1280)
    assert rep.dim_ok is False
    assert rep.ok is False


def test_check_pooled_fails_on_nonfinite() -> None:
    pooled = np.zeros((4, 8), dtype=np.float32)
    pooled[1, 2] = np.nan
    rep = check_pooled(pooled, expected_dim=8)
    assert rep.all_finite is False
    assert rep.ok is False


def test_mean_pool_rejects_empty() -> None:
    with pytest.raises(ValueError):
        mean_pool([])
