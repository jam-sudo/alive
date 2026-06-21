"""Tests for alive.metrics.distance — written FIRST per TDD protocol.

All tests are pure-numpy: no data files are read.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.distance import cdist

from alive.metrics.distance import (
    DistanceError,
    _deterministic_halves,
    energy_distance,
    equal_cell_sample,
    repeated_energy_distance,
    self_distance_floor,
    sliced_wasserstein,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Pre-computed fixed arrays used as parametrize inputs.  We freeze these
# at module-import time from a single fresh RNG so collection order never
# affects their values (each draw is a separate .standard_normal call on an
# RNG that is used only here and then discarded).
_PARAM_RNG = np.random.default_rng(0)
_PARAM_X_20_5 = _PARAM_RNG.standard_normal((20, 5))
_PARAM_X_1_3 = _PARAM_RNG.standard_normal((1, 3))
_PARAM_X_100_50 = _PARAM_RNG.standard_normal((100, 50))


def _brute_energy_distance(x: np.ndarray, y: np.ndarray) -> float:
    """Reference implementation: full pairwise cdist, V-statistic convention (divide by n²).

    E(X,Y) = 2*mean_{i,j}||xi - yj|| - mean_{i,i'}||xi - xi'|| - mean_{j,j'}||yj - yj'||

    The means are V-statistics (divide by n² / m²), which keeps E(X,X) = 0.
    """
    n = len(x)
    m = len(y)
    cross = np.sum(cdist(x, y, metric="euclidean")) / (n * m)
    within_x = np.sum(cdist(x, x, metric="euclidean")) / (n * n)
    within_y = np.sum(cdist(y, y, metric="euclidean")) / (m * m)
    result = 2.0 * cross - within_x - within_y
    return float(max(0.0, result))


# ---------------------------------------------------------------------------
# energy_distance — identity
# ---------------------------------------------------------------------------


class TestEnergyDistanceIdentity:
    """E(X, X) must equal 0 (within tolerance)."""

    @pytest.mark.parametrize(
        "x",
        [
            _PARAM_X_20_5,
            _PARAM_X_1_3,
            np.zeros((10, 8)),
            _PARAM_X_100_50,
        ],
    )
    def test_identity(self, x: np.ndarray) -> None:
        assert energy_distance(x, x) == pytest.approx(0.0, abs=1e-10)


# ---------------------------------------------------------------------------
# energy_distance — symmetry
# ---------------------------------------------------------------------------


class TestEnergyDistanceSymmetry:
    def test_symmetry_small(self) -> None:
        rng = np.random.default_rng(1)
        x = rng.standard_normal((15, 4))
        y = rng.standard_normal((15, 4))
        assert energy_distance(x, y) == pytest.approx(energy_distance(y, x), rel=1e-10)

    def test_symmetry_rectangular(self) -> None:
        """Symmetry must hold even when len(x) != len(y)."""
        rng = np.random.default_rng(2)
        x = rng.standard_normal((20, 6))
        y = rng.standard_normal((30, 6))
        assert energy_distance(x, y) == pytest.approx(energy_distance(y, x), rel=1e-10)


# ---------------------------------------------------------------------------
# energy_distance — non-negativity and shift monotonicity
# ---------------------------------------------------------------------------


class TestEnergyDistanceMonotonicity:
    """Translating Y further from X must yield larger energy distance."""

    def test_non_negative_and_shift_monotone(self) -> None:
        rng = np.random.default_rng(3)
        x = rng.standard_normal((25, 5))
        y = rng.standard_normal((25, 5))
        direction = rng.standard_normal(5)
        direction /= np.linalg.norm(direction)

        distances = []
        for t in [0.0, 0.5, 1.5, 3.0, 7.0]:
            y_shifted = y + t * direction
            d = energy_distance(x, y_shifted)
            assert d >= 0.0, f"Negative energy distance at t={t}: {d}"
            distances.append(d)

        # Strictly increasing with t (once t > 0 the shift adds separation)
        for i in range(1, len(distances)):
            assert distances[i] >= distances[i - 1], (
                f"Not non-decreasing: distances[{i}]={distances[i]} "
                f"< distances[{i - 1}]={distances[i - 1]}"
            )

        # Largest shift gives strictly larger distance than smallest positive shift
        assert distances[-1] > distances[1], (
            "Largest shift did not produce strictly larger distance than smallest positive shift"
        )


# ---------------------------------------------------------------------------
# energy_distance — dense reference (headline blocking-correctness test)
# ---------------------------------------------------------------------------


class TestEnergyDistanceBlockingCorrectness:
    """energy_distance with various block_size values must match brute-force cdist reference."""

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        rng = np.random.default_rng(42)
        self.x = rng.standard_normal((40, 8))
        self.y = rng.standard_normal((35, 8))
        self.ref = _brute_energy_distance(self.x, self.y)

    @pytest.mark.parametrize(
        "block_size",
        [
            4,  # many blocks (much smaller than n)
            10,  # multiple blocks
            20,  # roughly half of n
            40,  # equals n
            128,  # larger than n (single block)
            256,  # default
        ],
    )
    def test_matches_reference(self, block_size: int) -> None:
        result = energy_distance(self.x, self.y, block_size=block_size)
        assert result == pytest.approx(self.ref, rel=1e-9, abs=1e-12), (
            f"block_size={block_size}: got {result}, expected {self.ref}"
        )

    def test_reference_identity(self) -> None:
        """Brute-force reference should give ~0 for X vs X."""
        ref_self = _brute_energy_distance(self.x, self.x)
        assert ref_self == pytest.approx(0.0, abs=1e-10)

    def test_blocked_identity(self) -> None:
        """Blocked implementation should give ~0 for X vs X."""
        assert energy_distance(self.x, self.x, block_size=7) == pytest.approx(0.0, abs=1e-10)

    def test_larger_shift_matches_reference(self) -> None:
        """Reference and blocked must agree after a shift."""
        y_shifted = self.y + 5.0
        ref_shifted = _brute_energy_distance(self.x, y_shifted)
        blocked = energy_distance(self.x, y_shifted, block_size=5)
        assert blocked == pytest.approx(ref_shifted, rel=1e-9, abs=1e-12)


# ---------------------------------------------------------------------------
# equal_cell_sample
# ---------------------------------------------------------------------------


class TestEqualCellSample:
    def test_correct_n_rows(self) -> None:
        rng = np.random.default_rng(0)
        cells = rng.standard_normal((100, 5))
        sampled = equal_cell_sample(cells, 30, seed_key=7)
        assert sampled.shape == (30, 5)

    def test_no_replacement(self) -> None:
        """All sampled rows must be distinct (no duplicate row indices).

        We use integer-valued cells where each row is a unique integer so that
        row-value equality ↔ index equality — no false positives from coincidental
        float collisions.
        """
        # Each row is [i, i, i] so row values are unique by construction.
        cells = np.arange(50 * 3, dtype=np.float64).reshape(50, 3)
        sampled = equal_cell_sample(cells, 50, seed_key=99)
        # With integer-valued distinct rows, tuple uniqueness == index uniqueness.
        row_hashes = {tuple(r) for r in sampled}
        assert len(row_hashes) == 50

    def test_determinism(self) -> None:
        rng = np.random.default_rng(0)
        cells = rng.standard_normal((80, 4))
        a = equal_cell_sample(cells, 20, seed_key="abc")
        b = equal_cell_sample(cells, 20, seed_key="abc")
        np.testing.assert_array_equal(a, b)

    def test_different_seed_different_result(self) -> None:
        rng = np.random.default_rng(0)
        cells = rng.standard_normal((80, 4))
        a = equal_cell_sample(cells, 20, seed_key="abc")
        b = equal_cell_sample(cells, 20, seed_key="xyz")
        assert not np.array_equal(a, b), "Different seeds should yield different samples"

    def test_too_many_cells_raises(self) -> None:
        rng = np.random.default_rng(0)
        cells = rng.standard_normal((10, 3))
        with pytest.raises(DistanceError):
            equal_cell_sample(cells, 11, seed_key=0)

    def test_exact_n_works(self) -> None:
        rng = np.random.default_rng(0)
        cells = rng.standard_normal((10, 3))
        sampled = equal_cell_sample(cells, 10, seed_key=0)
        assert sampled.shape[0] == 10


# ---------------------------------------------------------------------------
# repeated_energy_distance
# ---------------------------------------------------------------------------


class TestRepeatedEnergyDistance:
    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        rng = np.random.default_rng(0)
        self.x = rng.standard_normal((200, 10))
        self.y = rng.standard_normal((200, 10))

    def test_determinism(self) -> None:
        a = repeated_energy_distance(
            self.x, self.y, cell_cap=50, min_cells=10, repeats=4, block_size=32, seed_key=42
        )
        b = repeated_energy_distance(
            self.x, self.y, cell_cap=50, min_cells=10, repeats=4, block_size=32, seed_key=42
        )
        assert a == pytest.approx(b)

    def test_uses_min_of_cap_nx_ny(self) -> None:
        """With a very large cap, all available cells should be used (no error)."""
        small_x = self.x[:30]
        small_y = self.y[:20]
        # cap=96, min(96,30,20)=20 which is >= min_cells=10
        result = repeated_energy_distance(
            small_x, small_y, cell_cap=96, min_cells=10, repeats=3, block_size=32, seed_key=1
        )
        assert result >= 0.0

    def test_raises_when_too_few_cells(self) -> None:
        small_x = self.x[:5]
        small_y = self.y[:5]
        # min(96,5,5)=5 < min_cells=10
        with pytest.raises(DistanceError, match="5"):
            repeated_energy_distance(
                small_x, small_y, cell_cap=96, min_cells=10, repeats=4, block_size=32, seed_key=0
            )

    def test_result_within_per_repeat_range(self) -> None:
        """The mean must equal the mean of per-repeat distances (not just be finite).

        We reproduce the EXACT per-repeat seeds that repeated_energy_distance uses
        internally:
            per_seed = (seed_key, r)
            x_sub = equal_cell_sample(x, n, seed_key=(per_seed, "x"))
            y_sub = equal_cell_sample(y, n, seed_key=(per_seed, "y"))

        so we can compute each repeat's energy distance ourselves and assert that
        repeated_energy_distance(..., repeats=5) equals np.mean(per_repeat_values).
        We also check that the mean lies within [min, max] of the per-repeat values.
        """
        cap, min_c, block, seed = 40, 10, 32, "sanity_range"
        n = min(cap, len(self.x), len(self.y))  # mirrors repeated_energy_distance logic

        per_repeat_values: list[float] = []
        for r in range(5):
            per_seed = (seed, r)
            x_sub = equal_cell_sample(self.x, n, seed_key=(per_seed, "x"))
            y_sub = equal_cell_sample(self.y, n, seed_key=(per_seed, "y"))
            per_repeat_values.append(energy_distance(x_sub, y_sub, block_size=block))

        mean_val = repeated_energy_distance(
            self.x,
            self.y,
            cell_cap=cap,
            min_cells=min_c,
            repeats=5,
            block_size=block,
            seed_key=seed,
        )

        expected_mean = float(np.mean(per_repeat_values))
        assert mean_val == pytest.approx(expected_mean, rel=1e-12, abs=1e-15), (
            f"repeated_energy_distance returned {mean_val}, "
            f"expected mean of per-repeat values {expected_mean}"
        )
        # Also verify mean lies within [min, max] of per-repeat distances
        assert min(per_repeat_values) <= mean_val <= max(per_repeat_values) + 1e-15, (
            f"Mean {mean_val} lies outside per-repeat range "
            f"[{min(per_repeat_values)}, {max(per_repeat_values)}]"
        )

    def test_non_negative(self) -> None:
        result = repeated_energy_distance(
            self.x, self.y, cell_cap=80, min_cells=10, repeats=5, block_size=64, seed_key="pos"
        )
        assert result >= 0.0

    def test_different_seed_key_different_result(self) -> None:
        a = repeated_energy_distance(
            self.x, self.y, cell_cap=50, min_cells=10, repeats=4, block_size=32, seed_key="s1"
        )
        b = repeated_energy_distance(
            self.x, self.y, cell_cap=50, min_cells=10, repeats=4, block_size=32, seed_key="s2"
        )
        # Very unlikely to be equal with different seeds
        assert a != pytest.approx(b)


# ---------------------------------------------------------------------------
# self_distance_floor
# ---------------------------------------------------------------------------


class TestSelfDistanceFloor:
    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        rng = np.random.default_rng(0)
        self.tight_cloud = rng.standard_normal((200, 10)) * 0.01
        self.diffuse_cloud = rng.standard_normal((200, 10)) * 10.0

    def test_determinism(self) -> None:
        a = self_distance_floor(
            self.tight_cloud, cell_cap=80, min_cells=10, repeats=4, block_size=32, seed_key="det"
        )
        b = self_distance_floor(
            self.tight_cloud, cell_cap=80, min_cells=10, repeats=4, block_size=32, seed_key="det"
        )
        assert a == pytest.approx(b)

    def test_halves_are_disjoint(self) -> None:
        """Directly verify that each repeat's two half-index arrays are disjoint and equal-size.

        We use _deterministic_halves with the same per-repeat seed keys that
        self_distance_floor uses internally (seed_key=(master, r)), and assert:
          (a) both halves have equal length (N // 2), and
          (b) the intersection of their index sets is empty.
        """
        N = len(self.diffuse_cloud)
        master_key = "disjoint_direct"
        for r in range(4):
            per_seed = (master_key, r)
            half1_idx, half2_idx = _deterministic_halves(self.diffuse_cloud, seed_key=per_seed)
            # (a) equal size
            assert len(half1_idx) == len(half2_idx), (
                f"Repeat {r}: half1 size {len(half1_idx)} != half2 size {len(half2_idx)}"
            )
            assert len(half1_idx) == N // 2, (
                f"Repeat {r}: expected half size {N // 2}, got {len(half1_idx)}"
            )
            # (b) disjoint
            shared = set(half1_idx.tolist()) & set(half2_idx.tolist())
            assert shared == set(), (
                f"Repeat {r}: halves share indices {shared} — halves are NOT disjoint"
            )

    def test_tight_cloud_smaller_than_diffuse(self) -> None:
        floor_tight = self_distance_floor(
            self.tight_cloud,
            cell_cap=80,
            min_cells=10,
            repeats=4,
            block_size=32,
            seed_key="compare",
        )
        floor_diffuse = self_distance_floor(
            self.diffuse_cloud,
            cell_cap=80,
            min_cells=10,
            repeats=4,
            block_size=32,
            seed_key="compare",
        )
        assert floor_tight < floor_diffuse, (
            f"Tight cloud floor ({floor_tight}) should be < diffuse cloud floor ({floor_diffuse})"
        )

    def test_raises_too_few_cells(self) -> None:
        rng = np.random.default_rng(0)
        tiny = rng.standard_normal((4, 5))
        # cell_cap//2=5, min_cells//2=5, half size = 2 < 5
        with pytest.raises(DistanceError):
            self_distance_floor(
                tiny, cell_cap=10, min_cells=10, repeats=2, block_size=32, seed_key=0
            )

    def test_non_negative(self) -> None:
        floor = self_distance_floor(
            self.tight_cloud, cell_cap=80, min_cells=10, repeats=3, block_size=32, seed_key="nn"
        )
        assert floor >= 0.0


# ---------------------------------------------------------------------------
# sliced_wasserstein
# ---------------------------------------------------------------------------


class TestSlicedWasserstein:
    def test_determinism(self) -> None:
        rng = np.random.default_rng(0)
        x = rng.standard_normal((50, 5))
        y = rng.standard_normal((50, 5))
        a = sliced_wasserstein(x, y, n_projections=20, seed_key=7)
        b = sliced_wasserstein(x, y, n_projections=20, seed_key=7)
        assert a == pytest.approx(b)

    def test_identity_approx_zero(self) -> None:
        """SW(X, X) == 0 exactly (same object, same projections)."""
        rng = np.random.default_rng(0)
        x = rng.standard_normal((50, 5))
        result = sliced_wasserstein(x, x, n_projections=30, seed_key=0)
        assert result == pytest.approx(0.0, abs=1e-10)

    def test_near_identity_two_draws_from_same_distribution(self) -> None:
        """SW should be small (< 1.0) for two large samples from the same N(0,I) distribution
        and strictly smaller than SW between two well-separated distributions.

        This exercises the equal-size path (n == m) with genuinely distinct arrays,
        unlike test_identity_approx_zero which compares X to itself.
        """
        rng = np.random.default_rng(12345)
        x = rng.standard_normal((200, 5))
        y = rng.standard_normal((200, 5))
        y_far = y + 10.0  # clearly separated from x

        sw_near = sliced_wasserstein(x, y, n_projections=50, seed_key=0)
        sw_far = sliced_wasserstein(x, y_far, n_projections=50, seed_key=0)

        assert sw_near < 1.0, f"SW between same-distribution draws too large: {sw_near}"
        assert sw_far > sw_near, (
            f"Separated clouds ({sw_far}) should give larger SW than same-distribution ({sw_near})"
        )

    def test_grows_with_shift(self) -> None:
        rng = np.random.default_rng(0)
        x = rng.standard_normal((50, 5))
        y = rng.standard_normal((50, 5))
        d_small = sliced_wasserstein(x, y + 1.0, n_projections=30, seed_key=0)
        d_large = sliced_wasserstein(x, y + 10.0, n_projections=30, seed_key=0)
        assert d_large > d_small, (
            f"Larger shift ({d_large}) should give larger SW distance "
            f"than smaller shift ({d_small})"
        )

    def test_non_negative(self) -> None:
        rng = np.random.default_rng(0)
        x = rng.standard_normal((30, 4))
        y = rng.standard_normal((30, 4))
        assert sliced_wasserstein(x, y, n_projections=20, seed_key=0) >= 0.0

    def test_different_seed_key_usually_different(self) -> None:
        rng = np.random.default_rng(0)
        x = rng.standard_normal((50, 5))
        y = rng.standard_normal((50, 5))
        a = sliced_wasserstein(x, y, n_projections=20, seed_key=1)
        b = sliced_wasserstein(x, y, n_projections=20, seed_key=2)
        # Different random projections, so result will almost certainly differ
        assert a != pytest.approx(b)

    def test_unequal_sizes(self) -> None:
        """SW should work for unequal-size clouds (uses scipy.stats.wasserstein_distance)."""
        rng = np.random.default_rng(0)
        x = rng.standard_normal((30, 4))
        y = rng.standard_normal((50, 4))
        result = sliced_wasserstein(x, y, n_projections=20, seed_key=0)
        assert result >= 0.0


# ---------------------------------------------------------------------------
# seed-key stability across processes (sha256, not builtin hash())
# ---------------------------------------------------------------------------


class TestSeedKeyStability:
    """Verify that the seed derivation is stable across Python processes.

    We do this by: (1) running a subprocess that computes the sha256-derived
    seed and prints it, then comparing to our local computation.  This
    guarantees PYTHONHASHSEED independence.
    """

    def test_sha256_seed_stable_across_processes(self) -> None:
        """The sha256-based seed must be identical in a fresh subprocess."""
        seed_key = "test_stability_seed"
        # Compute locally using documented formula
        local_seed = int.from_bytes(hashlib.sha256(str(seed_key).encode()).digest()[:8], "big")

        # Compute in a subprocess with a different PYTHONHASHSEED
        code = (
            "import hashlib; "
            f"seed_key = {seed_key!r}; "
            "result = int.from_bytes("
            "hashlib.sha256(str(seed_key).encode()).digest()[:8], 'big'"
            "); print(result)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env={**__import__("os").environ, "PYTHONHASHSEED": "12345"},
        )
        assert result.returncode == 0, f"Subprocess failed: {result.stderr}"
        subprocess_seed = int(result.stdout.strip())
        assert local_seed == subprocess_seed, (
            f"SHA256 seed mismatch: local={local_seed}, subprocess={subprocess_seed}"
        )

    def test_repeated_energy_distance_stable_across_processes(self) -> None:
        """repeated_energy_distance must be identical in a subprocess with different hash seed."""
        code = (
            "import sys, os; "
            "sys.path.insert(0, 'src'); "
            "import numpy as np; "
            "from alive.metrics.distance import repeated_energy_distance; "
            "rng = np.random.default_rng(77); "
            "x = rng.standard_normal((50, 5)); "
            "y = rng.standard_normal((50, 5)); "
            "r = repeated_energy_distance(x, y, cell_cap=30, min_cells=10, "
            "repeats=3, block_size=16, seed_key='stable_test'); "
            "print(f'{r:.15f}')"
        )
        # Derive the project root portably: tests/alive/metrics/test_distance.py → root
        _project_root = str(Path(__file__).parent.parent.parent.parent)

        env1 = {**os.environ, "PYTHONHASHSEED": "1"}
        env2 = {**os.environ, "PYTHONHASHSEED": "99999"}

        res1 = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env=env1,
            cwd=_project_root,
        )
        res2 = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env=env2,
            cwd=_project_root,
        )
        assert res1.returncode == 0, f"Process 1 failed: {res1.stderr}"
        assert res2.returncode == 0, f"Process 2 failed: {res2.stderr}"
        assert res1.stdout.strip() == res2.stdout.strip(), (
            f"Cross-process seed instability: "
            f"PYTHONHASHSEED=1 -> {res1.stdout.strip()}, "
            f"PYTHONHASHSEED=99999 -> {res2.stdout.strip()}"
        )
