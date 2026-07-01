"""Real calibration diagnostics + futility checkpoint (Task 2a-9; spec §10.6).

SYNTHETIC-ONLY: pure ``numpy`` on synthetic inputs only; **NO seal access**.
This module runs the Phase-2a development checkpoint on
**development-role inputs only** (``singles_train`` + ``combo_calibration``) and
decides whether the real study may CONTINUE or must be ``FUTILITY_STOPPED``
*before* any sealed outcome is opened.

What it computes (all on development inputs):

* the actual :math:`\\Phi` **rank** and **condition number** for the SELECTED
  total factor dimension (spec §10.4: the gate uses the real design-matrix rank,
  not a pair-count floor) via :func:`alive.compose.identify.rank_diagnostics`;
* the retained **singular-value spectrum** of :math:`\\Phi` and the **rank
  tolerance** used to threshold it;
* **split-half measurability** with an EXPLICIT development role, via
  :func:`alive.compose.gates.measurability_gate` (which refuses sealed roles);
* the **OOF primary theta** (L1 vs additive) via
  :func:`alive.compose.select.select_hyperparams` on calibration pairs.

Decision (spec §10.6 Phase-2a futility):

    ``CONTINUE`` iff EVERY registered gate passes — full rank AND finite
    conditioning AND measurable AND OOF theta ``> 0``.

    Otherwise ``FUTILITY_STOPPED``: rank deficiency OR non-finite conditioning OR
    measurability failure OR OOF theta ``<= 0``.

Seal discipline (spec §4.5 / §6.3 / §10.6). The result is a
:class:`FutilityResult` that records ``sealed_access_count == 0`` and carries **no
sealed-verdict field**. A ``FUTILITY_STOPPED`` development stop is therefore
structurally distinct from the sealed-axis ``NO_DISTINCT_WIN`` and the two can
never be confused or interconverted.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from alive.compose.gates import GateResult, measurability_gate
from alive.compose.identify import RankReport, rank_diagnostics
from alive.compose.operator import design_matrix
from alive.compose.select import ModelFactory, select_hyperparams

#: Status values this checkpoint may emit. Deliberately disjoint from the sealed
#: verdict axis ({GI_LEARNABLE_WIN, PARTIAL, NO_DISTINCT_WIN, INVALID}) so a
#: development stop can never be read as a sealed negative verdict.
_CONTINUE = "CONTINUE"
_FUTILITY_STOPPED = "FUTILITY_STOPPED"


@dataclass(frozen=True)
class FutilityResult:
    """Phase-2a development-checkpoint outcome (NO sealed verdict, spec §10.6).

    This is the *development* axis only. It is intentionally **not** a sealed
    verdict: it carries no ``sealed_verdict`` / ``verdict`` field and its
    ``status`` is one of ``{"CONTINUE", "FUTILITY_STOPPED"}`` — never a sealed-axis
    value such as ``NO_DISTINCT_WIN``. ``sealed_access_count`` is fixed at ``0``;
    a futility stop permanently terminates with the seal closed (spec §2.5).

    Attributes
    ----------
    status
        ``"CONTINUE"`` iff every registered gate passes, else
        ``"FUTILITY_STOPPED"``.
    sealed_access_count
        Always ``0``. This checkpoint opens no seal; the field exists to make the
        zero-access discipline explicit and auditable.
    rank_report
        Algebraic-identifiability diagnostics (rank, ``sym_dim``, full-rank flag,
        condition number) of the calibration design matrix :math:`\\Phi` at the
        SELECTED total factor dimension.
    singular_values
        Retained singular-value spectrum of :math:`\\Phi` (descending, length
        ``sym_dim`` of the selected dimension).
    rank_tolerance
        The numerical tolerance used to count nonzero singular values (the same
        ``max(shape) * eps * sigma_max`` rule :func:`rank_diagnostics` uses).
    measurability
        The split-half measurability :class:`~alive.compose.gates.GateResult`,
        computed with an explicit development role.
    oof_theta
        Out-of-fold primary theta (L1 vs additive) of the selected candidate.
    selected_k_total
        The total factor dimension selected by gene-disjoint OOF.
    selected_lambda
        The ridge regularization selected by gene-disjoint OOF.
    failures
        Human-readable reasons the checkpoint stopped (empty iff ``CONTINUE``).
    """

    status: str
    sealed_access_count: int
    rank_report: RankReport
    singular_values: np.ndarray
    rank_tolerance: float
    measurability: GateResult
    oof_theta: float
    selected_k_total: int
    selected_lambda: float
    failures: tuple[str, ...] = field(default=())


def _spectrum_and_tol(Z: np.ndarray, pairs: Sequence[tuple[int, int]]) -> tuple[np.ndarray, float]:
    """Singular-value spectrum of the calibration design matrix and its rank tol.

    Mirrors the tolerance rule in :func:`alive.compose.identify.rank_diagnostics`
    (``max(shape) * float64-eps * sigma_max``) so the retained spectrum and the
    rank count reported by ``rank_diagnostics`` are threshold-consistent.

    Parameters
    ----------
    Z
        Per-gene factor matrix of shape ``(n_genes, k_total)``.
    pairs
        Calibration gene-index pairs (order-irrelevant; the bilinear pair feature
        is symmetric).

    Returns
    -------
    (numpy.ndarray, float)
        The descending singular values of :math:`\\Phi` and the rank tolerance.
    """
    phi = design_matrix(np.asarray(Z, dtype=np.float64), list(pairs))
    svals = np.linalg.svd(phi, compute_uv=False)
    sigma_max = float(svals[0]) if svals.size else 0.0
    tol = float(max(phi.shape) * np.finfo(np.float64).eps * sigma_max)
    return np.asarray(svals, dtype=np.float64), tol


def real_calibration_diagnostics(
    *,
    idx_pairs: Sequence[tuple[int, int]],
    pair_ids: Sequence[tuple[str, str]],
    eps_obs: np.ndarray,
    additive: np.ndarray,
    factors_by_k: dict[int, np.ndarray],
    k_total_grid: Sequence[int],
    lambda_grid: Sequence[float],
    n_genes: int,
    n_folds: int,
    seed: int,
    model_factory: ModelFactory,
    uncovered_tolerance: float,
    eps_split_a: np.ndarray,
    eps_split_b: np.ndarray,
    dev_oof_threshold: float = 0.0,
    measurability_role: str = "combo_calibration",
) -> FutilityResult:
    r"""Run the Phase-2a development checkpoint on development-role inputs only.

    Steps (spec §10.4 / §10.6), all on development calibration data:

    1. select ``(k_total, lambda)`` and the OOF primary theta (L1 vs additive) by
       gene-disjoint OOF on the calibration pairs
       (:func:`alive.compose.select.select_hyperparams`);
    2. compute the real :math:`\Phi` rank and condition number at the SELECTED
       total factor dimension (:func:`alive.compose.identify.rank_diagnostics`)
       and retain the singular-value spectrum + rank tolerance;
    3. compute split-half measurability with an EXPLICIT development role
       (:func:`alive.compose.gates.measurability_gate`, which refuses sealed
       roles);
    4. emit ``CONTINUE`` iff full rank AND finite conditioning AND measurable AND
       OOF theta ``> 0``; otherwise ``FUTILITY_STOPPED``.

    Parameters
    ----------
    idx_pairs, pair_ids, eps_obs, additive, factors_by_k, k_total_grid,
    lambda_grid, n_genes, n_folds, seed, model_factory, uncovered_tolerance
        Development calibration inputs forwarded to
        :func:`alive.compose.select.select_hyperparams` (see its docstring). The
        additive comparator is response-dimensional (length ``p``), never
        factor-shaped.
    eps_split_a, eps_split_b
        Development split-half GI (epsilon) estimates for the measurability gate.
    measurability_role
        Explicit development role forwarded to the measurability gate. A sealed
        role raises :class:`~alive.compose.gates.LeakageError` (no sealed read).

    Returns
    -------
    FutilityResult
        ``status`` plus the rank report, retained spectrum/tolerance,
        measurability result, OOF theta and the selected hyperparameters.
        ``sealed_access_count`` is always ``0`` and there is no sealed-verdict
        field.

    Raises
    ------
    alive.compose.gates.LeakageError
        If ``measurability_role`` names a sealed role.
    alive.compose.select.SelectionError
        On any invalid selection input or an invalidating fold layout.
    """
    # 3 (run first so a sealed-role request fails fast before any compute):
    # split-half measurability with an EXPLICIT development role. The gate refuses
    # sealed roles, so a leakage attempt raises here (no sealed outcome is read).
    measurability = measurability_gate(eps_split_a, eps_split_b, _role=measurability_role)

    # 1: gene-disjoint OOF selection -> selected (k_total, lambda) + OOF theta.
    selection = select_hyperparams(
        idx_pairs=idx_pairs,
        pair_ids=pair_ids,
        eps_obs=eps_obs,
        additive=additive,
        factors_by_k=factors_by_k,
        k_total_grid=k_total_grid,
        lambda_grid=lambda_grid,
        n_genes=n_genes,
        n_folds=n_folds,
        seed=seed,
        model_factory=model_factory,
        uncovered_tolerance=uncovered_tolerance,
    )
    selected_k_total = selection.selected_k_total
    selected_lambda = selection.selected_lambda
    oof_theta = float(selection.theta_by_candidate[(selected_k_total, selected_lambda)])

    # 2: real Phi rank + condition number at the SELECTED dimension (§10.4 — the
    # gate uses the actual design-matrix rank, not a pair-count floor), plus the
    # retained singular-value spectrum and the rank tolerance.
    Z_selected = np.asarray(factors_by_k[selected_k_total], dtype=np.float64)
    rank_report = rank_diagnostics(Z_selected, list(idx_pairs))
    singular_values, rank_tolerance = _spectrum_and_tol(Z_selected, idx_pairs)

    # 4: decision. CONTINUE only when EVERY registered gate passes.
    failures: list[str] = []
    if not rank_report.is_full_rank:
        failures.append(
            f"rank deficiency: rank {rank_report.rank} < sym_dim {rank_report.sym_dim} "
            "(identifiable subspace only; cannot identify full operator)"
        )
    if not np.isfinite(rank_report.condition_number):
        failures.append(
            "non-finite conditioning: calibration design is ill-conditioned "
            f"(condition_number={rank_report.condition_number})"
        )
    if not measurability.passed:
        failures.append(
            f"measurability failure: GI signal at/below noise floor "
            f"(ceiling={measurability.detail.get('ceiling')})"
        )
    if oof_theta <= float(dev_oof_threshold):
        failures.append(
            "OOF primary theta does not clear the preregistered threshold: "
            f"theta={oof_theta}, threshold={float(dev_oof_threshold)}"
        )

    status = _CONTINUE if not failures else _FUTILITY_STOPPED

    return FutilityResult(
        status=status,
        sealed_access_count=0,
        rank_report=rank_report,
        singular_values=singular_values,
        rank_tolerance=rank_tolerance,
        measurability=measurability,
        oof_theta=oof_theta,
        selected_k_total=selected_k_total,
        selected_lambda=selected_lambda,
        failures=tuple(failures),
    )
