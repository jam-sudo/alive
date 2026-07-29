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


def identify_operator(
    Z: np.ndarray,
    pairs: list[tuple[int, int]],
    eps_obs: np.ndarray,
    *,
    lam: float = 0.0,
) -> np.ndarray:
    """Estimate ``coef`` (p, sym_dim) by ridge least squares on the design matrix.

    Solves ``min_C ||Phi C^T - eps_obs||^2 + lam ||C||^2``. At ``lam == 0`` it
    uses the SVD minimum-norm least-squares solution with the same
    ``max(shape) * float64-eps * sigma_max`` cutoff as :func:`rank_diagnostics`;
    this defines Phase-1 rank-deficient recovery without relying on an arbitrary
    singular normal-equation result. Positive ridge penalties use
    ``(Phi^T Phi + lam I) C^T = Phi^T eps_obs``, and are rejected when the
    penalty is not representable against the Gram's scale (see below).

    Raises
    ------
    SingularDesignError
        If LAPACK cannot compute the least-squares/linear-system solution, or if
        a positive ``lam`` leaves every Gram diagonal entry unchanged — at that
        factor scale the registered ridge is numerically a no-op, so the design
        that would be solved is the unregularized one. Phase-2a OOF selection
        applies its registered train-fold rank policy before fitting, and
        records a candidate rejected here as non-viable rather than scoring it.
    """
    Z = np.asarray(Z, dtype=np.float64)
    eps_obs = np.asarray(eps_obs, dtype=np.float64)
    lam = float(lam)
    if not np.isfinite(lam) or lam < 0.0:
        raise ValueError(f"lam must be finite and non-negative, got {lam!r}")

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

    base = phi.T @ phi
    gram = base + lam * np.eye(phi.shape[1])
    # Exact representability of the registered estimator -- NOT a tolerance, and
    # not a new registered numerical criterion. The penalty is added to each
    # diagonal entry independently, so a factor bank scaled far enough above
    # ``lam`` makes ``fl(d_ii + lam) == d_ii`` for EVERY i; the matrix actually
    # solved is then the unregularized Gram and a positive registered lambda has
    # been applied as no regularization at all. Nothing upstream bounds the
    # factor scale (`_verify_factor_banks` binds provenance, and the recorded
    # condition number is scale-invariant), so this is checked here rather than
    # assumed. Scope: it detects a penalty that vanished outright; it does not
    # certify the conditioning of a partially-rounded ridge, which is what the
    # rank and condition-number gates cover.
    diag_base = np.diag(base)
    if diag_base.size and np.array_equal(np.diag(gram), diag_base):
        raise SingularDesignError(
            f"ridge penalty lam={lam!r} is not representable against the calibration "
            f"Gram (largest diagonal {float(diag_base.max())!r}): adding lam*I left "
            "every diagonal entry unchanged, so the design that would be solved is "
            "the UNREGULARIZED one rather than the registered (Phi^T Phi + lam I)"
        )
    rhs = phi.T @ eps_obs
    try:
        coef_t = np.linalg.solve(gram, rhs)  # (sym_dim, p)
    except np.linalg.LinAlgError as exc:
        raise SingularDesignError(
            f"calibration design has no unique least-squares solution at lam={lam!r}: {exc}"
        ) from exc
    return coef_t.T
