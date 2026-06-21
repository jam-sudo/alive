"""Population-distance machinery for the ALIVE Trust-Gate MVP.

This module provides the equal-cell sampling and blocked energy-distance
computations that turn two cell-population arrays (in the 50-dim PCA response
space produced by Task 7) into scalar risk scores.

Energy-distance convention
--------------------------
We use the **V-statistic** form throughout:

    E(X, Y) = 2 * (1/n*m) * sum_{i,j} ||xi - yj||
              - (1/n²) * sum_{i,i'} ||xi - xi'||
              - (1/m²) * sum_{j,j'} ||yj - yj'||

Dividing within-X by n² (rather than n*(n-1)) ensures E(X, X) = 0 exactly
and keeps all three terms on the same footing.  The cross-term is divided by
n*m.  Tiny negative results from floating-point rounding are clamped to 0.

Seed-key determinism
--------------------
Every random Generator is seeded via a **stable SHA-256-based derivation**:

    seed = int.from_bytes(sha256(str(seed_key).encode()).digest()[:8], "big")

This is resilient to Python's per-process PYTHONHASHSEED salting, which
affects ``hash()`` but not ``hashlib``.

Blocked computation
-------------------
``energy_distance`` iterates row-blocks of X against row-blocks of Y (size
``block_size``), accumulating pairwise-distance sums without allocating the
full n×m distance matrix.

Public API
----------
DistanceError
    Raised for insufficient cells or invalid inputs.
energy_distance(x, y, *, block_size)
    Székely energy distance (V-statistic form, blocked).
sliced_wasserstein(x, y, *, n_projections, seed_key)
    Average 1-D Wasserstein-1 over random unit projections.
equal_cell_sample(cells, n, *, seed_key)
    Deterministic without-replacement row sampler.
repeated_energy_distance(x, y, *, cell_cap, min_cells, repeats, block_size, seed_key)
    Repeat-averaged, equal-cell energy distance (primary risk metric).
self_distance_floor(cells, *, cell_cap, min_cells, repeats, block_size, seed_key)
    Half-split noise-floor estimator (reliability diagnostic).

Examples
--------
>>> import numpy as np
>>> rng = np.random.default_rng(0)
>>> x = rng.standard_normal((100, 50))
>>> y = rng.standard_normal((100, 50))
>>> energy_distance(x, x)  # doctest: +ELLIPSIS
0.0
>>> energy_distance(x, y) > 0
True
"""

from __future__ import annotations

import hashlib

import numpy as np
from scipy.spatial.distance import cdist
from scipy.stats import wasserstein_distance

# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class DistanceError(ValueError):
    """Raised when cell counts are insufficient or inputs are invalid.

    Parameters
    ----------
    message : str
        Human-readable description of the problem.
    """


# ---------------------------------------------------------------------------
# Seed-key derivation (stable across Python processes)
# ---------------------------------------------------------------------------


def _stable_seed(seed_key: object) -> int:
    """Derive a stable integer seed from *seed_key* using SHA-256.

    Uses ``hashlib.sha256``, not Python's builtin ``hash()`` — the latter is
    salted per-process by PYTHONHASHSEED and is therefore non-reproducible
    across processes.

    Parameters
    ----------
    seed_key : object
        Any object whose ``str()`` representation is stable across sessions
        (e.g. an int, a string, or a tuple of those).

    Returns
    -------
    int
        A 64-bit non-negative integer derived deterministically from
        ``str(seed_key)``.
    """
    return int.from_bytes(hashlib.sha256(str(seed_key).encode()).digest()[:8], "big")


def _make_rng(seed_key: object) -> np.random.Generator:
    """Return a fresh ``np.random.Generator`` seeded deterministically from *seed_key*."""
    return np.random.default_rng(_stable_seed(seed_key))


# ---------------------------------------------------------------------------
# Blocked pairwise-distance accumulator
# ---------------------------------------------------------------------------


def _blocked_distance_sum(
    a: np.ndarray,
    b: np.ndarray,
    *,
    block_size: int,
) -> float:
    """Accumulate sum of pairwise Euclidean distances between rows of *a* and *b*.

    Iterates outer-product row-blocks of size ``block_size`` to bound peak
    memory to O(block_size²) rather than O(n*m).

    Parameters
    ----------
    a : np.ndarray
        Shape (n, d).
    b : np.ndarray
        Shape (m, d).
    block_size : int
        Number of rows per block.

    Returns
    -------
    float
        Sum of all n*m pairwise Euclidean distances (float64).
    """
    total: float = 0.0
    n = len(a)
    m = len(b)
    for i_start in range(0, n, block_size):
        a_block = a[i_start : i_start + block_size]
        for j_start in range(0, m, block_size):
            b_block = b[j_start : j_start + block_size]
            # cdist returns a (|a_block|, |b_block|) matrix of Euclidean distances
            total += float(np.sum(cdist(a_block, b_block, metric="euclidean")))
    return total


# ---------------------------------------------------------------------------
# Energy distance
# ---------------------------------------------------------------------------


def energy_distance(x: np.ndarray, y: np.ndarray, *, block_size: int = 256) -> float:
    """Székely energy distance between two point clouds (V-statistic form, blocked).

    .. math::

        E(X,Y) = 2\\,\\bar{d}_{XY} - \\bar{d}_{XX} - \\bar{d}_{YY}

    where

    .. math::

        \\bar{d}_{XY} = \\frac{1}{nm}\\sum_{i,j}\\|x_i - y_j\\|, \\quad
        \\bar{d}_{XX} = \\frac{1}{n^2}\\sum_{i,i'}\\|x_i - x_{i'}\\|

    (V-statistic: the self-sum includes the diagonal, which contributes 0 and
    keeps ``E(X, X) = 0`` exactly).  Pairwise sums are computed in row-blocks
    of ``block_size`` rows to bound peak memory.

    Parameters
    ----------
    x : np.ndarray
        Shape (n, d).  Rows are points, columns are PCA dimensions.
    y : np.ndarray
        Shape (m, d).  Rows are points, columns are PCA dimensions.
    block_size : int, optional
        Number of rows per block for the blocked pairwise accumulation
        (default: 256).

    Returns
    -------
    float
        Non-negative energy distance.  Tiny negative values from floating-point
        rounding are clamped to 0.0.

    Notes
    -----
    Convention: all three terms use V-statistic denominators (n², m², n*m).
    This makes ``energy_distance(X, X) == 0`` for any X.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)

    n = len(x)
    m = len(y)

    cross_sum = _blocked_distance_sum(x, y, block_size=block_size)
    within_x_sum = _blocked_distance_sum(x, x, block_size=block_size)
    within_y_sum = _blocked_distance_sum(y, y, block_size=block_size)

    # V-statistic means
    cross_mean = cross_sum / (n * m)
    within_x_mean = within_x_sum / (n * n)
    within_y_mean = within_y_sum / (m * m)

    result = 2.0 * cross_mean - within_x_mean - within_y_mean
    return float(max(0.0, result))


# ---------------------------------------------------------------------------
# Sliced Wasserstein (diagnostic)
# ---------------------------------------------------------------------------


def sliced_wasserstein(
    x: np.ndarray,
    y: np.ndarray,
    *,
    n_projections: int = 50,
    seed_key: object = 0,
) -> float:
    """Average 1-D Wasserstein-1 distance over random unit directions (diagnostic).

    For each of ``n_projections`` random unit vectors, both clouds are
    projected onto the vector, and the 1-D Wasserstein-1 distance between the
    projections is computed.  For equal-size samples this reduces to the mean
    of the sorted absolute differences; for unequal sizes
    ``scipy.stats.wasserstein_distance`` is used.

    Parameters
    ----------
    x : np.ndarray
        Shape (n, d).
    y : np.ndarray
        Shape (m, d).
    n_projections : int, optional
        Number of random unit directions to average over (default: 50).
    seed_key : object, optional
        Seed key for deterministic projection sampling (default: 0).

    Returns
    -------
    float
        Non-negative average sliced Wasserstein-1 distance.

    Notes
    -----
    This is a **diagnostic** metric only; the primary risk metric is
    ``repeated_energy_distance``.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)

    rng = _make_rng(seed_key)
    d = x.shape[1]
    n = len(x)
    m = len(y)

    # Sample random unit directions: (n_projections, d)
    directions = rng.standard_normal((n_projections, d))
    norms = np.linalg.norm(directions, axis=1, keepdims=True)
    directions /= norms  # unit vectors

    total: float = 0.0
    for v in directions:
        px = x @ v  # (n,)
        py = y @ v  # (m,)
        if n == m:
            # Fast path: sort both, compute mean |difference|
            px_sorted = np.sort(px)
            py_sorted = np.sort(py)
            total += float(np.mean(np.abs(px_sorted - py_sorted)))
        else:
            total += float(wasserstein_distance(px, py))

    return float(max(0.0, total / n_projections))


# ---------------------------------------------------------------------------
# Deterministic equal-cell sampling
# ---------------------------------------------------------------------------


def equal_cell_sample(cells: np.ndarray, n: int, *, seed_key: object) -> np.ndarray:
    """Sample *n* rows from *cells* without replacement, deterministically.

    Parameters
    ----------
    cells : np.ndarray
        Shape (N, d).  The pool of cells to sample from.
    n : int
        Number of rows to return.
    seed_key : object
        Seed key for deterministic, cross-process-stable sampling.

    Returns
    -------
    np.ndarray
        Shape (n, d) — a subset of rows from *cells*.

    Raises
    ------
    DistanceError
        If ``n > len(cells)``.
    """
    cells = np.asarray(cells, dtype=np.float64)
    N = len(cells)
    if n > N:
        raise DistanceError(
            f"Requested {n} cells but only {N} are available; cannot sample without replacement."
        )
    rng = _make_rng(seed_key)
    idx = rng.choice(N, size=n, replace=False)
    return cells[idx]


# ---------------------------------------------------------------------------
# Repeated equal-cell energy distance (primary risk metric)
# ---------------------------------------------------------------------------


def repeated_energy_distance(
    x: np.ndarray,
    y: np.ndarray,
    *,
    cell_cap: int,
    min_cells: int,
    repeats: int,
    block_size: int,
    seed_key: object,
) -> float:
    """Equal-cell, repeat-averaged energy distance (primary risk metric).

    Algorithm
    ---------
    1. Compute ``n = min(cell_cap, len(x), len(y))``.
    2. If ``n < min_cells``, raise :class:`DistanceError` naming the deficit.
    3. For each repeat ``r`` in ``range(repeats)``:
       - Subsample ``n`` rows from each of *x* and *y* without replacement,
         using a per-repeat seed derived from ``(seed_key, r)``.
       - Compute ``energy_distance`` on the pair.
    4. Return the **mean** over the ``repeats`` distances.

    Parameters
    ----------
    x : np.ndarray
        Shape (nx, d).
    y : np.ndarray
        Shape (ny, d).
    cell_cap : int
        Maximum cells used per population per repeat.
    min_cells : int
        Minimum cells required; raises if ``min(cell_cap, nx, ny) < min_cells``.
    repeats : int
        Number of independent resampling rounds to average.
    block_size : int
        Block size passed to ``energy_distance``.
    seed_key : object
        Master seed key; per-repeat seeds are derived from ``(seed_key, r)``.

    Returns
    -------
    float
        Non-negative mean energy distance over *repeats* rounds.

    Raises
    ------
    DistanceError
        If the effective cell count falls below *min_cells*.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)

    n = min(cell_cap, len(x), len(y))
    if n < min_cells:
        raise DistanceError(
            f"Effective cell count {n} is below min_cells={min_cells}. "
            f"cell_cap={cell_cap}, len(x)={len(x)}, len(y)={len(y)}."
        )

    distances: list[float] = []
    for r in range(repeats):
        per_seed = (seed_key, r)
        x_sub = equal_cell_sample(x, n, seed_key=(per_seed, "x"))
        y_sub = equal_cell_sample(y, n, seed_key=(per_seed, "y"))
        distances.append(energy_distance(x_sub, y_sub, block_size=block_size))

    return float(np.mean(distances))


# ---------------------------------------------------------------------------
# Self-distance floor (reliability diagnostic)
# ---------------------------------------------------------------------------


def _deterministic_halves(
    cells: np.ndarray,
    *,
    seed_key: object,
) -> tuple[np.ndarray, np.ndarray]:
    """Return the two disjoint half-index arrays produced by a single shuffle-and-split.

    This is the documented split rule used inside :func:`self_distance_floor` for a
    single repeat *r*: call with ``seed_key=(master_key, r)`` to reproduce repeat *r*
    exactly.  Exposed as a semi-private helper so tests can verify disjointness and
    equal size without accessing internals.

    Parameters
    ----------
    cells : np.ndarray
        Shape (N, d).
    seed_key : object
        Seed key for the shuffle (matches the per-repeat key used internally).

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        ``(half1_idx, half2_idx)`` — the index arrays of the two halves.  Both
        have length ``N // 2``.  They are always disjoint by construction (non-
        overlapping slices of a permutation).
    """
    N = len(cells)
    half_available = N // 2
    rng = _make_rng(seed_key)
    shuffled_idx = rng.permutation(N)
    half1_idx = shuffled_idx[:half_available]
    half2_idx = shuffled_idx[half_available : 2 * half_available]
    return half1_idx, half2_idx


def self_distance_floor(
    cells: np.ndarray,
    *,
    cell_cap: int,
    min_cells: int,
    repeats: int,
    block_size: int,
    seed_key: object,
) -> float:
    """Deterministic half-split noise floor (reliability diagnostic).

    For each of *repeats* rounds:

    1. Deterministically **shuffle** all cells using seed ``(seed_key, r)``.
    2. **Split** the shuffled cells into two disjoint halves.
    3. Draw ``half_n = min(cell_cap // 2, len(half))`` cells from each half.
       Require ``half_n >= min_cells // 2``; raise :class:`DistanceError` if not.
    4. Compute ``energy_distance`` on the two sub-sampled halves.

    Return the **mean** over *repeats* rounds.

    Sizing rule: ``half_n = min(cell_cap // 2, N // 2)`` where N = len(cells).
    This is the largest symmetric sub-sample that respects the per-population
    cap and stays within the available cells.  Both halves always have the same
    size ``half_n``.

    Parameters
    ----------
    cells : np.ndarray
        Shape (N, d).  The population to measure the noise floor of.
    cell_cap : int
        Maximum cells per population (halved for each split half).
    min_cells : int
        Minimum cells threshold (halved for each split half).
    repeats : int
        Number of independent shuffle-and-split rounds to average.
    block_size : int
        Block size passed to ``energy_distance``.
    seed_key : object
        Master seed key; per-repeat seeds are derived from ``(seed_key, r)``.

    Returns
    -------
    float
        Non-negative mean self-distance over *repeats* rounds.

    Raises
    ------
    DistanceError
        If ``half_n < min_cells // 2``.

    Notes
    -----
    This is a **reliability diagnostic** estimating the irreducible
    within-population variation at finite sample size.  It is **not** an
    exclusion criterion.
    """
    cells = np.asarray(cells, dtype=np.float64)
    N = len(cells)

    # Each half receives at most cell_cap//2 cells and at most N//2 cells
    half_cap = cell_cap // 2
    half_available = N // 2
    half_n = min(half_cap, half_available)

    min_half = min_cells // 2
    if half_n < min_half:
        raise DistanceError(
            f"Per-half cell count {half_n} is below min_cells//2={min_half}. "
            f"cell_cap//2={half_cap}, N//2={half_available}."
        )

    distances: list[float] = []
    for r in range(repeats):
        # Shuffle to create two disjoint halves (use the shared helper for testability)
        half1_idx, half2_idx = _deterministic_halves(cells, seed_key=(seed_key, r))

        half1 = cells[half1_idx]
        half2 = cells[half2_idx]

        # Sub-sample half_n from each half (deterministically)
        sub1 = equal_cell_sample(half1, half_n, seed_key=((seed_key, r), "h1"))
        sub2 = equal_cell_sample(half2, half_n, seed_key=((seed_key, r), "h2"))

        distances.append(energy_distance(sub1, sub2, block_size=block_size))

    return float(np.mean(distances))
