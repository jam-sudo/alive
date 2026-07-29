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
        a positive ``lam`` leaves any Gram diagonal entry unchanged — on those
        coordinates the registered ridge is numerically absent, so the design
        that would be solved is not ``(Phi^T Phi + lam I)``. Phase-2a OOF
        selection applies its registered train-fold rank policy before fitting,
        and records a candidate rejected here as non-viable rather than scoring
        it.

        Scope. A coordinate is lost when ``lam < ulp(d_ii)/2``, and at the tie
        ``lam == ulp(d_ii)/2`` only when ``d_ii``'s last mantissa bit is even;
        no registered lambda is dyadic, so the tie is unreachable here.
        Wherever the penalty survives it is still quantized to a multiple of
        ``ulp(d_ii)``, and the ratio actually applied is lambda-specific:
        measured over all surviving scales, ``applied/lam`` spans
        ``[0.977, 1.953]`` at ``lam=0.001``, ``[0.781, 1.563]`` at ``0.01`` and
        ``[0.938, 1.250]`` at ``0.1``. A registered lambda can therefore be
        applied ~22% below its registered value with this check silent, so "the
        design solved is the registered one" is not certified — only "no
        coordinate lost its penalty outright". Ordinary ill-conditioning is
        likewise out of scope: a well-represented ``lam`` can still be
        immaterial to the fit. Non-finite
        ``Z``: ``inf`` diagonals compare equal and DO reject; ``NaN`` compares
        unequal to itself and does not, so this is not fail-closed under NaN
        (the factor builder rejects non-finite inputs upstream).
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
    # diagonal entry independently, so on a factor bank scaled far enough above
    # ``lam`` the addition rounds away and ``fl(d_ii + lam) == d_ii``: on those
    # coordinates the design that gets solved carries no penalty at all, and a
    # positive registered lambda has been applied as something other than
    # itself. Rejecting on ANY such coordinate rather than on all of them is
    # deliberate. ``z`` concatenates an expression block and an ESM block, so a
    # single over-scaled block loses the penalty only on the basis elements that
    # involve it -- an all-coordinates rule cannot fire on exactly the input
    # whose scale nothing upstream bounds. It also makes this reproducible from
    # committed evidence: ``design_matrix`` rows satisfy
    # ``||row||**2 = (||z_g||**2 ||z_h||**2 + (z_g . z_h)**2) / 2 <= max||z||**4``
    # by Cauchy-Schwarz, and ``d_ii <= sum_i d_ii = sum_pairs ||row||**2``, so
    # ``d_ii <= n_pairs * max||z||**4`` with constant 1 sharp (attained by
    # ``z_g = z_h = M e_1`` on every pair). The firing scale therefore follows
    # from the pair count alone, without the (uncommitted) Gram spectrum.
    #
    # Nothing upstream bounds that scale: ``_verify_factor_banks`` binds
    # provenance only, the registered OOF rank policy is keyed to the literal
    # ``lam == 0.0`` and so never runs for a ridge candidate, and
    # ``rank_diagnostics`` uses a tolerance relative to ``sigma_max`` and is
    # therefore exactly scale-invariant -- its rank and condition number are
    # unchanged across many orders of magnitude of ``||z||``. No registered
    # diagnostic observes this, which is why it is checked at the point of use.
    diag_base = np.diag(base)
    n_lost = int(np.sum(np.diag(gram) == diag_base))
    if n_lost:
        raise SingularDesignError(
            f"ridge penalty lam={lam!r} is not representable against the calibration "
            f"Gram on {n_lost} of {diag_base.size} coordinates: adding lam*I left those "
            "diagonal entries unchanged, so the design that would be solved is not the "
            "registered (Phi^T Phi + lam I). The factor bank is scaled too far above "
            "the registered penalty for that penalty to be applied as registered"
        )
    rhs = phi.T @ eps_obs
    try:
        coef_t = np.linalg.solve(gram, rhs)  # (sym_dim, p)
    except np.linalg.LinAlgError as exc:
        raise SingularDesignError(
            f"calibration design has no unique least-squares solution at lam={lam!r}: {exc}"
        ) from exc
    return coef_t.T
