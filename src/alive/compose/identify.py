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


class SingularDesignError(ValueError):
    """The registered least-squares solver failed to produce an estimate.

    A LAPACK least-squares/solve failure is normalized to this type. Phase-specific
    callers that require full-rank input (notably Phase-2a OOF selection) apply
    their registered rank policy before calling this general estimator; Phase 1
    also uses the minimum-norm solution deliberately to characterize
    rank-deficient recovery.
    """


#: Exact positive-ridge implementation pinned by the Phase-2 config.  The
#: filter-factor form applies lambda to singular values directly and never forms
#: ``Phi.T @ Phi``, whose squaring of the condition number can erase a small
#: registered penalty before the solve starts.
REGULARIZED_SOLVER = "svd_ridge_filter_factors"


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
    # A rank-deficient design has a zero singular value, so it is effectively
    # infinitely conditioned. Reporting the ratio over only the positive singular
    # values would misleadingly read "well-conditioned"; report inf instead.
    if rank < sym_dim or pos.size == 0:
        cond = float("inf")
    else:
        cond = float(pos[0] / pos[-1])
    return RankReport(
        sym_dim=sym_dim,
        rank=rank,
        is_full_rank=rank >= sym_dim,
        condition_number=cond,
    )


def solve_ridge_svd(design: np.ndarray, target: np.ndarray, *, lam: float) -> np.ndarray:
    """Solve positive ridge regression with stable SVD filter factors.

    Returns ``argmin_W ||design W - target||² + lam ||W||²``.  Computing
    ``s / (s² + lam)`` naively can itself overflow or underflow; the two algebraic
    branches below keep every division in a bounded ratio while applying the
    registered ``lam`` without constructing normal equations.
    """
    design = np.asarray(design, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    lam = float(lam)
    if not np.isfinite(lam) or lam <= 0.0:
        raise ValueError(f"lam must be finite and positive for ridge SVD, got {lam!r}")
    if design.ndim != 2 or design.shape[0] == 0 or design.shape[1] == 0:
        raise ValueError(f"design must be a non-empty 2-D matrix, got shape {design.shape!r}")
    if target.ndim == 1:
        target = target[:, np.newaxis]
    if target.ndim != 2 or target.shape[0] != design.shape[0]:
        raise ValueError(
            "target must be 1-D/2-D and row-aligned with design: "
            f"design={design.shape!r}, target={target.shape!r}"
        )
    if not np.all(np.isfinite(design)) or not np.all(np.isfinite(target)):
        raise ValueError("ridge design and target must contain only finite values")

    try:
        u, singular_values, vt = np.linalg.svd(design, full_matrices=False)
    except np.linalg.LinAlgError as exc:
        raise SingularDesignError(f"regularized SVD solver failed at lam={lam!r}: {exc}") from exc
    if not (
        np.all(np.isfinite(u)) and np.all(np.isfinite(singular_values)) and np.all(np.isfinite(vt))
    ):
        raise SingularDesignError(
            f"regularized SVD solver produced a non-finite decomposition at lam={lam!r}"
        )

    root_lam = float(np.sqrt(lam))
    gains = np.empty_like(singular_values)
    large = singular_values >= root_lam
    # s >= sqrt(lam): (1/s) / (1 + lam/s²), avoiding s² overflow.
    gains[large] = (1.0 / singular_values[large]) / (1.0 + (root_lam / singular_values[large]) ** 2)
    # s < sqrt(lam): (s/lam) / (1 + s²/lam), including s == 0.
    gains[~large] = (singular_values[~large] / lam) / (
        1.0 + (singular_values[~large] / root_lam) ** 2
    )
    solution = (vt.T * gains) @ (u.T @ target)
    if not np.all(np.isfinite(solution)):
        raise SingularDesignError(
            f"regularized SVD solver produced a non-finite estimate at lam={lam!r}"
        )
    return np.asarray(solution, dtype=np.float64)


def identify_operator(
    Z: np.ndarray,
    pairs: list[tuple[int, int]],
    eps_obs: np.ndarray,
    *,
    lam: float = 0.0,
) -> np.ndarray:
    """Estimate ``coef`` (p, sym_dim) by ridge least squares.

    ``lam == 0`` uses the registered SVD minimum-norm least-squares cutoff.
    Positive penalties use :data:`REGULARIZED_SOLVER`: SVD filter factors on
    ``Phi`` itself.  This avoids both condition-number squaring and the prior
    ``Phi.T @ Phi + lam I`` failure mode where floating-point addition silently
    erased or quantized the registered penalty on large factor coordinates.
    """
    Z = np.asarray(Z, dtype=np.float64)
    eps_obs = np.asarray(eps_obs, dtype=np.float64)
    lam = float(lam)
    if not np.isfinite(lam) or lam < 0.0:
        raise ValueError(f"lam must be finite and non-negative, got {lam!r}")
    if Z.ndim != 2 or Z.shape[0] == 0 or Z.shape[1] == 0:
        raise ValueError(f"Z must be a non-empty 2-D matrix, got shape {Z.shape!r}")
    if eps_obs.ndim == 1:
        eps_obs = eps_obs[:, np.newaxis]
    if eps_obs.ndim != 2 or len(pairs) != eps_obs.shape[0] or not pairs:
        raise ValueError("eps_obs must be 1-D/2-D and row-aligned with a non-empty pair roster")
    if not np.all(np.isfinite(Z)) or not np.all(np.isfinite(eps_obs)):
        raise ValueError("Z and eps_obs must contain only finite values")

    phi = design_matrix(Z, pairs)
    if lam == 0.0:
        # np.linalg.lstsq's rcond is relative to sigma_max, so this value is the
        # same absolute threshold rank_diagnostics uses:
        # max(phi.shape) * eps * sigma_max. Same rule, not necessarily the same
        # verdict at the boundary -- rank_diagnostics goes through np.linalg.svd
        # (gesdd) and lstsq through gelsd, whose computed spectra differ in the
        # last bits.
        rcond = float(max(phi.shape) * np.finfo(np.float64).eps)
        try:
            coef_t, _, _, _ = np.linalg.lstsq(phi, eps_obs, rcond=rcond)
        except np.linalg.LinAlgError as exc:
            raise SingularDesignError(
                f"unregularized least-squares solver failed at lam={lam!r}: {exc}"
            ) from exc
        return coef_t.T

    return solve_ridge_svd(phi, eps_obs, lam=lam).T
