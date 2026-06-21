"""Staged real fit / develop / calibrate / sealed-evaluation integration (Task 16).

This module wires the leakage-safe components built in Tasks 3-15 into four
staged functions plus three shared helpers.  It is the INTEGRATION layer that
enforces the project's life-or-death integrity properties:

1. **Leakage boundary (hard).** :func:`fit_base`, :func:`develop_methods_stage`,
   and :func:`calibrate` obtain observed populations exclusively through
   ``store.read_controls`` and ``store.read_unsealed`` — they NEVER call
   ``evaluate_sealed_once`` and never request a sealed id.  After all three
   stages, ``store.sealed_access_count`` is still ``0``.
2. **Scores before risks.** :func:`evaluate_sealed_once` computes ALL method
   scores and base predictions from FEATURES (no seal access) BEFORE the single
   ``store.evaluate_sealed_once`` call.  Sealed *risks* are computed only after
   the seal is opened.
3. **Futility forbids sealed evaluation.** When the futility decision is
   ``FUTILITY_STOPPED``, :func:`evaluate_sealed_once` raises immediately and the
   seal is never opened.
4. **The seal opens exactly once.** Exactly one ``store.evaluate_sealed_once``
   call is made (and the durable Task-5 audit enforces once-per-run_id).

The actual K562 data run happens on the A100 via Task 17's CLI; here the stages
are exercised on synthetic data only.

Public API
----------
measured_error(...)
    Per-perturbation RISK = energy distance between base prediction and observed.
perturbation_inputs(...)
    Aligned (ids, features, errors, ensemble_means) over a population dict.
gate_and_comparator_scores(...)
    Fit every method on a reference bank and score a query set.
BaseArtifact
    Frozen response-space + base-predictor bundle (the ``fit_base`` output).
fit_base(...)
    Stage 1: fit ResponseSpace + BasePredictor on controls + base_train.
develop_methods_stage(...)
    Stage 2: OOF method development + futility decision on method_development.
calibrate(...)
    Stage 3: split-conformal artifact on conformal_calibration.
evaluate_sealed_once(...)
    Stage 4: the single audited sealed evaluation → :class:`VerdictResult`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from alive.base.predictor import BasePredictor, fit_base_predictor
from alive.baselines.uq import (
    EnsembleDisagreement,
    GbmErrorRegressor,
    NearestFeatureDistance,
    ResidualOnly,
    RidgeErrorRegressor,
)
from alive.conformal.error_bound import (
    ConformalArtifact,
    build_conformal_artifact,
    conformal_coverage_passes,
    coverage_report,
)
from alive.data.preprocess import ResponseSpace, fit_response_space
from alive.eval.bootstrap import confirmatory_inference
from alive.eval.verdict import IntegrityReport, VerdictResult, compute_verdict
from alive.experiment.develop import (
    METHOD_IDS,
    FutilityDecision,
    MethodLock,
    decide_futility,
    develop_methods,
)
from alive.gate.recoverability import TrustGate
from alive.metrics.distance import repeated_energy_distance, self_distance_floor
from alive.metrics.selective import normalize_by_mean, risk_coverage_curve
from alive.provenance import sha256_json
from alive.types import OperationalStatus, Query

if TYPE_CHECKING:
    from alive.config import Config
    from alive.config import ResponseSpace as ResponseSpaceCfg
    from alive.data.features import FeatureBank
    from alive.data.manifest import SplitManifest
    from alive.data.outcome_store import Population
    from alive.data.replogle import ReplogleIndex
    from alive.eval.bootstrap import ConfirmatoryInference
    from alive.provenance import RunLedger


# ---------------------------------------------------------------------------
# The 5 confirmatory comparator names (METHOD_IDS minus the gate reference).
# ---------------------------------------------------------------------------

#: Comparator family for confirmatory inference (gate is the reference).
COMPARATOR_NAMES: tuple[str, ...] = tuple(m for m in METHOD_IDS if m != "gate")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def measured_error(
    base: BasePredictor,
    response_space: ResponseSpace,
    features: np.ndarray,
    observed: "Population",
    *,
    response_cfg: "ResponseSpaceCfg",
    seed_key: object,
) -> float:
    """Compute the RISK for one perturbation: a population-distribution distance.

    The base predictor translates the control population by the predicted mean
    shift (in response space); the observed population is projected into the same
    response space.  The risk is the repeat-averaged equal-cell energy distance
    between the two clouds.

    Parameters
    ----------
    base : BasePredictor
        Fitted base predictor (Task 9).
    response_space : ResponseSpace
        Fitted response-space transform (Task 7).
    features : np.ndarray
        Standardized 1-D feature vector for this perturbation.
    observed : Population
        Observed (raw-count) cell population for this perturbation.
    response_cfg : ResponseSpaceCfg
        Response-space config section supplying ``cell_cap``, ``min_cells``,
        ``cell_sampling_repeats``, and ``energy_block_size``.
    seed_key : object
        Deterministic, cross-process-stable seed key for the energy-distance
        resampling (e.g. ``(run_id, perturbation_id)``).

    Returns
    -------
    float
        Non-negative energy-distance risk.
    """
    predicted = base.predict(Query(perturbation_id=observed.perturbation_id, features=features))
    predicted_rs = predicted.predicted_cells
    observed_rs = response_space.transform(np.asarray(observed.cells, dtype=np.float64))
    return repeated_energy_distance(
        predicted_rs,
        observed_rs,
        cell_cap=response_cfg.cell_cap,
        min_cells=response_cfg.min_cells,
        repeats=response_cfg.cell_sampling_repeats,
        block_size=response_cfg.energy_block_size,
        seed_key=seed_key,
    )


def perturbation_inputs(
    base: BasePredictor,
    response_space: ResponseSpace,
    feature_bank: "FeatureBank",
    populations: dict[str, "Population"],
    *,
    response_cfg: "ResponseSpaceCfg",
    run_id: str,
) -> tuple[tuple[str, ...], np.ndarray, np.ndarray, np.ndarray]:
    """Build aligned (ids, features, errors, ensemble_means) over *populations*.

    For each id (in SORTED order) that the feature bank carries: take its
    standardized feature vector, the base predictor's per-member ensemble means,
    and the measured energy-distance risk.  Ids the bank lacks are skipped.

    Parameters
    ----------
    base : BasePredictor
        Fitted base predictor.
    response_space : ResponseSpace
        Fitted response-space transform.
    feature_bank : FeatureBank
        Per-perturbation feature bank.
    populations : dict[str, Population]
        Observed populations keyed by perturbation id (e.g. from
        ``store.read_unsealed(ids)``).
    response_cfg : ResponseSpaceCfg
        Response-space config section.
    run_id : str
        Deterministic run id; per-id seed keys are derived from ``(run_id, id)``.

    Returns
    -------
    tuple[tuple[str, ...], np.ndarray, np.ndarray, np.ndarray]
        ``(ids, features, errors, ensemble_means)`` where ``features`` has shape
        ``(n, feat_dim)``, ``errors`` has shape ``(n,)``, and ``ensemble_means``
        has shape ``(n, n_members, pca_dims)`` — all row-aligned with ``ids``.
    """
    ids: list[str] = []
    feats: list[np.ndarray] = []
    errs: list[float] = []
    ens_means: list[np.ndarray] = []

    for pid in sorted(populations):
        if not feature_bank.has(pid):
            continue
        feat = np.asarray(feature_bank.standardized_vector(pid), dtype=np.float64)
        pred = base.predict(Query(perturbation_id=pid, features=feat))
        err = measured_error(
            base,
            response_space,
            feat,
            populations[pid],
            response_cfg=response_cfg,
            seed_key=(run_id, pid),
        )
        ids.append(pid)
        feats.append(feat)
        errs.append(float(err))
        ens_means.append(np.asarray(pred.ensemble_member_means, dtype=np.float64))

    if not ids:
        raise ValueError(
            "perturbation_inputs: no requested population is present in the feature bank."
        )

    features = np.stack(feats, axis=0)
    errors = np.asarray(errs, dtype=np.float64)
    ensemble_means = np.stack(ens_means, axis=0)
    return tuple(ids), features, errors, ensemble_means


def gate_and_comparator_scores(
    method_lock: MethodLock,
    base: BasePredictor,
    ref_features: np.ndarray,
    ref_errors: np.ndarray,
    ref_ensemble_means: np.ndarray,
    query_features: np.ndarray,
    query_ensemble_means: np.ndarray,
) -> dict[str, np.ndarray]:
    """Fit every method on the REFERENCE bank, then score the query set.

    The reference bank is ALWAYS the method_development bank (``ref_*``); the
    callers never pass calibration/sealed data here.  Each method is fitted at
    its ``method_lock.selected_params`` and produces one score per query
    (higher = abstain).  ``ensemble_disagreement`` scores from
    ``query_ensemble_means`` (output space); all others score from
    ``query_features``.

    Parameters
    ----------
    method_lock : MethodLock
        Developed methods + selected hyperparameters (Task 12).
    base : BasePredictor
        Fitted base predictor (accepted for API symmetry; ensemble means are
        passed in directly as ``*_ensemble_means``).
    ref_features : np.ndarray
        Shape ``(n_ref, feat_dim)`` method_development features.
    ref_errors : np.ndarray
        Shape ``(n_ref,)`` method_development measured risks.
    ref_ensemble_means : np.ndarray
        Shape ``(n_ref, n_members, pca_dims)`` (accepted for symmetry; the
        ensemble_disagreement comparator is fit-free).
    query_features : np.ndarray
        Shape ``(n_query, feat_dim)`` query features.
    query_ensemble_means : np.ndarray
        Shape ``(n_query, n_members, pca_dims)`` query ensemble means.

    Returns
    -------
    dict[str, np.ndarray]
        ``method_name -> (n_query,)`` score array, one entry per
        :data:`~alive.experiment.develop.METHOD_IDS`.
    """
    ref_features = np.asarray(ref_features, dtype=np.float64)
    ref_errors = np.asarray(ref_errors, dtype=np.float64)
    query_features = np.asarray(query_features, dtype=np.float64)
    query_ensemble_means = np.asarray(query_ensemble_means, dtype=np.float64)

    params = method_lock.selected_params
    scores: dict[str, np.ndarray] = {}

    for method in METHOD_IDS:
        p = params[method]
        if method == "gate":
            scorer = TrustGate.fit(ref_features, ref_errors, k=p["k"], w=p["w"])
            scores[method] = np.asarray(scorer.score(query_features), dtype=np.float64)
        elif method == "residual_only":
            scorer = ResidualOnly().fit(ref_features, ref_errors, k=p["k"])
            scores[method] = np.asarray(scorer.score(query_features), dtype=np.float64)
        elif method == "nearest_feature":
            scorer = NearestFeatureDistance().fit(ref_features, ref_errors)
            scores[method] = np.asarray(scorer.score(query_features), dtype=np.float64)
        elif method == "ridge_error":
            scorer = RidgeErrorRegressor().fit(ref_features, ref_errors, alpha=p["alpha"])
            scores[method] = np.asarray(scorer.score(query_features), dtype=np.float64)
        elif method == "gbm_error":
            # Use a registered seed for reproducibility of the GBM refit.
            seed = int(method_lock.registered_seeds[0])
            scorer = GbmErrorRegressor().fit(
                ref_features, ref_errors, n_estimators=p["n_estimators"], seed=seed
            )
            scores[method] = np.asarray(scorer.score(query_features), dtype=np.float64)
        elif method == "ensemble_disagreement":
            scorer = EnsembleDisagreement().fit(ref_features, ref_errors)
            scores[method] = np.asarray(scorer.score(query_ensemble_means), dtype=np.float64)
        else:  # pragma: no cover - guarded by METHOD_IDS
            raise ValueError(f"Unknown method {method!r}.")

    return scores


# ---------------------------------------------------------------------------
# BaseArtifact (Stage 1 output)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BaseArtifact:
    """Bundled response space + base predictor produced by :func:`fit_base`.

    Parameters
    ----------
    response_space : ResponseSpace
        Fitted response-space transform (Task 7).
    base_predictor : BasePredictor
        Fitted additive-ridge base predictor (Task 9).
    """

    response_space: ResponseSpace
    base_predictor: BasePredictor

    @cached_property
    def checksum(self) -> str:
        """SHA-256 over the response-space and base-predictor checksums.

        Returns
        -------
        str
            64-character lowercase hexadecimal SHA-256 digest.
        """
        return sha256_json(
            {
                "response_space": self.response_space.checksum,
                "base_predictor": self.base_predictor.checksum,
            }
        )


# ---------------------------------------------------------------------------
# Stage 1 — fit_base
# ---------------------------------------------------------------------------


def fit_base(
    index: "ReplogleIndex",
    store: object,
    manifest: "SplitManifest",
    feature_bank: "FeatureBank",
    config: "Config",
) -> BaseArtifact:
    """Stage 1: fit the response space and base predictor (leakage-safe).

    The response space (Task 7) and base predictor (Task 9) share the same
    fit-set: controls + ``base_train`` populations.  Both are obtained via
    ``read_controls`` + ``read_unsealed`` ONLY; ``evaluate_sealed_once`` is never
    called and no sealed id is ever requested.

    Parameters
    ----------
    index : ReplogleIndex
        Metadata index (Task 3).
    store : OutcomeStore-like
        Sealed outcome store; only ``read_controls`` / ``read_unsealed`` used.
    manifest : SplitManifest
        Split manifest (Task 4).
    feature_bank : FeatureBank
        Per-perturbation feature bank (Task 6).
    config : Config
        Locked experiment config (Task 1).

    Returns
    -------
    BaseArtifact
        Bundled response space + base predictor.
    """
    rs_cfg = config.response_space
    response_space = fit_response_space(
        index,
        store,
        manifest,
        normalization=rs_cfg.normalization,
        target_sum=10000.0,
        hvg_count=rs_cfg.hvg_count,
        pca_dims=rs_cfg.pca_dims,
    )
    base_predictor = fit_base_predictor(
        manifest,
        store,
        response_space,
        feature_bank,
        ridge_grid=config.base_model.ridge_grid,
        cv_folds=config.base_model.cv_folds,
        ensemble_members=config.base_model.ensemble_members,
        seed=config.manifest_seed,
    )
    return BaseArtifact(response_space=response_space, base_predictor=base_predictor)


# ---------------------------------------------------------------------------
# Stage 2 — develop_methods_stage
# ---------------------------------------------------------------------------


def develop_methods_stage(
    index: "ReplogleIndex",
    store: object,
    manifest: "SplitManifest",
    base_artifact: BaseArtifact,
    feature_bank: "FeatureBank",
    config: "Config",
    *,
    run_id: str,
    config_sha256: str | None = None,
) -> tuple[MethodLock, FutilityDecision]:
    """Stage 2: OOF method development + preregistered futility decision.

    Computes the method_development (ids, features, errors, ensemble_means) via
    ``read_unsealed`` ONLY, runs :func:`develop_methods` (Task 12) to lock the
    methods, then applies :func:`decide_futility` on the dev-normalized errors.
    The sealed cohort is never touched.

    Parameters
    ----------
    index : ReplogleIndex
        Metadata index.
    store : OutcomeStore-like
        Outcome store; only ``read_unsealed`` is used here.
    manifest : SplitManifest
        Split manifest.
    base_artifact : BaseArtifact
        The Stage-1 response space + base predictor.
    feature_bank : FeatureBank
        Per-perturbation feature bank.
    config : Config
        Locked experiment config.
    run_id : str
        The COMPOSITE immutable run id (spec §4.5) used to seed the deterministic
        equal-cell sampling of the ``method_development`` errors.  REQUIRED: it
        MUST match the value used by :func:`calibrate` / :func:`evaluate_sealed_once`
        for the shared reference bank, otherwise the conformal threshold silently
        desynchronises from the sealed scores.  The CLI threads the composite
        run_id; unit tests pass ``config.config_digest``.

    Returns
    -------
    tuple[MethodLock, FutilityDecision]
        The locked methods and the futility decision.
    """
    # Sampling seed source: the required composite run_id (spec §4.5).  MUST
    # match the value used by calibrate / evaluate_sealed_once for the shared
    # method_development bank, or the conformal threshold desynchronises.
    seed_run_id = run_id

    dev_ids = [pid for pid in manifest.ids_for("method_development") if feature_bank.has(pid)]
    populations = store.read_unsealed(dev_ids)
    ids, features, errors, ensemble_means = perturbation_inputs(
        base_artifact.base_predictor,
        base_artifact.response_space,
        feature_bank,
        populations,
        response_cfg=config.response_space,
        run_id=seed_run_id,
    )

    md = config.method_development
    # Provenance link to the locked config: the CLI threads the FULL config
    # digest (sha256 of the config file); pure unit tests fall back to run_id.
    config_sha = config_sha256 if config_sha256 is not None else config.config_digest
    method_lock = develop_methods(
        ids,
        features,
        errors,
        ensemble_means,
        cv_folds=md.cv_folds,
        k_grid=md.k_grid,
        feature_weight_grid=md.feature_weight_grid,
        ridge_grid=md.ridge_grid,
        gbm_estimators_grid=md.gbm_estimators_grid,
        registered_seeds=md.registered_seeds,
        config_sha256=config_sha,
    )

    norm_errors = normalize_by_mean(errors)
    futility = decide_futility(
        method_lock,
        norm_errors,
        comparators=config.futility.comparators,
        delta_min=config.futility.minimum_relevant_delta,
        confidence=config.futility.family_confidence,
        n_replicates=config.inference.bootstrap_replicates,
        seed=config.manifest_seed,
        config_sha256=config_sha,
    )
    return method_lock, futility


# ---------------------------------------------------------------------------
# Stage 3 — calibrate
# ---------------------------------------------------------------------------


def calibrate(
    index: "ReplogleIndex",
    store: object,
    manifest: "SplitManifest",
    base_artifact: BaseArtifact,
    method_lock: MethodLock,
    feature_bank: "FeatureBank",
    config: "Config",
    *,
    run_id: str,
    config_sha256: str | None = None,
) -> ConformalArtifact:
    """Stage 3: build the split-conformal artifact on conformal_calibration.

    Computes the calibration errors and the fitted-gate scores on the
    ``conformal_calibration`` split (reference = method_development), then calls
    :func:`build_conformal_artifact` (Task 13).  Uses ``read_unsealed`` ONLY.

    Parameters
    ----------
    index : ReplogleIndex
        Metadata index.
    store : OutcomeStore-like
        Outcome store; only ``read_unsealed`` is used.
    manifest : SplitManifest
        Split manifest.
    base_artifact : BaseArtifact
        Stage-1 response space + base predictor.
    method_lock : MethodLock
        Stage-2 locked methods.
    feature_bank : FeatureBank
        Per-perturbation feature bank.
    config : Config
        Locked experiment config.
    run_id : str
        The COMPOSITE immutable run id (spec §4.5) used to seed the deterministic
        equal-cell sampling of the shared ``method_development`` reference bank
        (and the calibration query set).  REQUIRED: this MUST be the same value
        :func:`evaluate_sealed_once` is called with so the gate/comparator scorers
        fitted at calibration and at sealed evaluation are byte-identical — the
        conformal coverage guarantee assumes one identically-fitted model, so a
        mismatch silently desynchronises the threshold from the sealed scores.
        The CLI always threads the composite run_id; unit tests pass
        ``config.config_digest``.
    config_sha256 : str or None
        Full 64-char SHA-256 digest of the locked config file.  The CLI
        always passes this; pure unit tests may omit it (falls back to
        ``config.config_digest`` so existing tests remain valid).

    Returns
    -------
    ConformalArtifact
        The bundled, checksummed conformal calibration artifact.
    """
    base = base_artifact.base_predictor
    rs = base_artifact.response_space

    # The sampling seed source: the required composite run_id (spec §4.5).
    # MUST match the value used by evaluate_sealed_once for the shared reference
    # bank, or the gate scorer fitted here diverges from the sealed one.
    seed_run_id = run_id

    # Reference bank = method_development (never calibration/sealed).
    ref_ids = [pid for pid in manifest.ids_for("method_development") if feature_bank.has(pid)]
    ref_pops = store.read_unsealed(ref_ids)
    _ref_ids, ref_features, ref_errors, ref_ensemble_means = perturbation_inputs(
        base,
        rs,
        feature_bank,
        ref_pops,
        response_cfg=config.response_space,
        run_id=seed_run_id,
    )

    # Calibration query set.
    cal_ids = [pid for pid in manifest.ids_for("conformal_calibration") if feature_bank.has(pid)]
    cal_pops = store.read_unsealed(cal_ids)
    _cal_ids, cal_features, cal_errors, cal_ensemble_means = perturbation_inputs(
        base,
        rs,
        feature_bank,
        cal_pops,
        response_cfg=config.response_space,
        run_id=seed_run_id,
    )

    cal_scores = gate_and_comparator_scores(
        method_lock,
        base,
        ref_features,
        ref_errors,
        ref_ensemble_means,
        cal_features,
        cal_ensemble_means,
    )
    cal_gate_scores = cal_scores["gate"]

    # Thread the full config digest like the other stages; fall back to
    # config.config_digest only for pure unit tests that do not pass the digest.
    cfg_sha = config_sha256 if config_sha256 is not None else config.config_digest
    return build_conformal_artifact(
        cal_errors,
        cal_gate_scores,
        alpha=config.decision.conformal_alpha,
        target_selection_coverage=config.decision.target_selection_coverage,
        config_sha256=cfg_sha,
    )


# ---------------------------------------------------------------------------
# Provenance verification (carry-forward fix a)
# ---------------------------------------------------------------------------

#: Artifact names whose recorded ledger hash must match the in-memory checksum
#: for ``provenance_ok`` to hold.  Each is recorded by an earlier CLI stage.
_PROVENANCE_ARTIFACTS: tuple[str, ...] = (
    "config",
    "split_manifest",
    "feature_bank",
    "base_artifact",
    "method_lock",
    "conformal_artifact",
)


def verify_provenance(
    ledger: "RunLedger | None",
    expected_checksums: dict[str, str],
    *,
    store: object,
    run_id: str,
) -> bool:
    """Verify the run's provenance chain against the recorded :class:`RunLedger`.

    ``provenance_ok`` is ``True`` iff the ledger exists AND every recorded
    artifact hash in :data:`_PROVENANCE_ARTIFACTS` that is present in the ledger
    verifies against the in-memory artifact's checksum (config, split manifest,
    feature bank, base/preprocessing, MethodLock, conformal) AND the
    sealed-access audit is consistent (exactly one recorded access carrying this
    ``run_id``).

    Parameters
    ----------
    ledger : RunLedger or None
        The run ledger built by the CLI.  ``None`` is a documented fallback for
        pure unit tests that do not exercise the provenance leg — in that case
        the check returns ``True`` (the CLI ALWAYS passes a real ledger so the
        provenance leg of the integrity gate genuinely fires).
    expected_checksums : dict[str, str]
        Map of artifact name → the checksum recomputed from the in-memory
        artifact this stage holds.  Only names present in BOTH the ledger and
        this map are compared; a tampered recorded hash → mismatch → ``False``.
    store : OutcomeStore-like
        The outcome store; its durable sealed-access audit is checked.
    run_id : str
        The deterministic run id; the audit must carry exactly this id once.

    Returns
    -------
    bool
        Whether the provenance chain is intact.
    """
    if ledger is None:
        # Documented fallback: pure unit tests that do not build a ledger.
        return True

    from alive.provenance import LedgerError

    for name in _PROVENANCE_ARTIFACTS:
        if name not in expected_checksums:
            continue
        try:
            recorded = ledger.artifact_sha(name)
        except LedgerError:
            # An expected artifact was never recorded → broken chain.
            return False
        if recorded != expected_checksums[name]:
            return False

    # Sealed-access audit consistency: exactly one access, carrying this run_id.
    try:
        records = store._read_audit_records()  # noqa: SLF001 — internal audit
    except Exception:  # noqa: BLE001
        return False
    if len(records) != 1:
        return False
    if records[0].get("run_id") != run_id:
        return False
    return True


# ---------------------------------------------------------------------------
# Stage 4 — evaluate_sealed_once (the integrity crux)
# ---------------------------------------------------------------------------


def evaluate_sealed_once(
    index: "ReplogleIndex",
    store: object,
    manifest: "SplitManifest",
    base_artifact: BaseArtifact,
    method_lock: MethodLock,
    conformal_artifact: ConformalArtifact,
    futility_decision: FutilityDecision,
    feature_bank: "FeatureBank",
    config: "Config",
    *,
    run_id: str,
    config_sha256: str | None = None,
    ledger: "RunLedger | None" = None,
    result_path: "str | Path | None" = None,
    require_encoder_match: bool = False,
) -> VerdictResult:
    """Stage 4: the single audited sealed evaluation → :class:`VerdictResult`.

    Implements the EXACT integrity ordering of the brief:

    1. Refuse if ``futility_decision.status == FUTILITY_STOPPED`` (raise
       ``RuntimeError``; the seal is never opened).
    2. Compute sealed features + ALL method scores BEFORE opening the seal — at
       this point ``store.sealed_access_count`` is still 0.
    3. Open the seal ONCE: ``store.evaluate_sealed_once(run_id, sealed_ids)``.
    4. Compute sealed RISKS (energy distances) + reliability floors.
    5. Build the :class:`IntegrityReport` (completeness, finiteness, sealed_n,
       reliability precondition).  If invalid, STILL proceed to
       :func:`compute_verdict` (it returns ``INVALID_EVALUATION``) and write the
       result — never silently dropped.
    6. Normalize risks + run :func:`confirmatory_inference`.
    7. Conformal coverage pass/fail + coverage report.
    8. :func:`compute_verdict`.
    9. Write the immutable result + (optional) ledger; return the verdict.

    Parameters
    ----------
    index : ReplogleIndex
        Metadata index.
    store : OutcomeStore-like
        Outcome store; opened exactly once via ``evaluate_sealed_once``.
    manifest : SplitManifest
        Split manifest (provides ``ids_for("sealed_evaluation")``).
    base_artifact : BaseArtifact
        Stage-1 response space + base predictor.
    method_lock : MethodLock
        Stage-2 locked methods.
    conformal_artifact : ConformalArtifact
        Stage-3 conformal artifact.
    futility_decision : FutilityDecision
        Stage-2 futility decision; ``FUTILITY_STOPPED`` forbids this call.
    feature_bank : FeatureBank
        Per-perturbation feature bank.
    config : Config
        Locked experiment config.
    run_id : str
        Deterministic run id used for the single sealed access.
    ledger : RunLedger or None, optional
        If provided, the verdict checksum is recorded in the ledger.
    result_path : str or Path or None, optional
        If provided, the :class:`VerdictResult` is written to this path.

    Returns
    -------
    VerdictResult
        The frozen scientific verdict.

    Raises
    ------
    RuntimeError
        If ``futility_decision.status == FUTILITY_STOPPED``.
    """
    # --- 1. Refuse if futility-stopped (the seal must never open here). -------
    if futility_decision.status == OperationalStatus.FUTILITY_STOPPED:
        raise RuntimeError(
            "evaluate_sealed_once is forbidden when futility_decision.status is "
            "FUTILITY_STOPPED; the sealed cohort must not be opened in that branch."
        )

    base = base_artifact.base_predictor
    rs = base_artifact.response_space
    rs_cfg = config.response_space

    # --- 2. Sealed FEATURES + SCORES, all computed BEFORE opening the seal. ---
    sealed_ids = tuple(
        pid for pid in manifest.ids_for("sealed_evaluation") if feature_bank.has(pid)
    )
    if len(sealed_ids) == 0:
        raise RuntimeError(
            "No sealed_evaluation perturbations are present in the feature bank; "
            "cannot run a sealed evaluation."
        )

    sealed_features = np.stack(
        [np.asarray(feature_bank.standardized_vector(pid), dtype=np.float64) for pid in sealed_ids],
        axis=0,
    )
    sealed_ensemble_means = np.stack(
        [
            np.asarray(
                base.predict(
                    Query(perturbation_id=pid, features=sealed_features[i])
                ).ensemble_member_means,
                dtype=np.float64,
            )
            for i, pid in enumerate(sealed_ids)
        ],
        axis=0,
    )

    # Recompute the method_development REFERENCE bank via read_unsealed (no seal).
    ref_ids = [pid for pid in manifest.ids_for("method_development") if feature_bank.has(pid)]
    ref_pops = store.read_unsealed(ref_ids)
    _ref_ids, ref_features, ref_errors, ref_ensemble_means = perturbation_inputs(
        base, rs, feature_bank, ref_pops, response_cfg=rs_cfg, run_id=run_id
    )

    method_scores = gate_and_comparator_scores(
        method_lock,
        base,
        ref_features,
        ref_errors,
        ref_ensemble_means,
        sealed_features,
        sealed_ensemble_means,
    )
    sealed_gate_scores = method_scores["gate"]

    # INVARIANT: the seal is still shut at this point.

    # --- 3. Open the seal ONCE. ----------------------------------------------
    observed = store.evaluate_sealed_once(run_id, list(sealed_ids))

    # --- 4. Sealed RISKS + reliability floors (in sorted id order). ----------
    risk_list: list[float] = []
    reliability_floors: list[float] = []
    missing_ids: list[str] = []
    risk_finite = True
    reliability_ok = True

    for i, pid in enumerate(sealed_ids):
        if pid not in observed:
            missing_ids.append(pid)
            continue
        pop = observed[pid]
        err = measured_error(
            base,
            rs,
            sealed_features[i],
            pop,
            response_cfg=rs_cfg,
            seed_key=(run_id, pid),
        )
        risk_list.append(float(err))
        if not np.isfinite(err):
            risk_finite = False
        # Reliability precondition: the self-distance floor must be finite/positive.
        try:
            floor = self_distance_floor(
                rs.transform(np.asarray(pop.cells, dtype=np.float64)),
                cell_cap=rs_cfg.cell_cap,
                min_cells=rs_cfg.min_cells,
                repeats=rs_cfg.cell_sampling_repeats,
                block_size=rs_cfg.energy_block_size,
                seed_key=(run_id, pid, "floor"),
            )
        except Exception:  # noqa: BLE001 — a failed floor is a reliability failure, not a crash
            floor = float("nan")
        reliability_floors.append(float(floor))
        if not (np.isfinite(floor) and floor > 0.0):
            reliability_ok = False

    risk = np.asarray(risk_list, dtype=np.float64)
    sealed_n = int(len(risk))

    # --- 5. Integrity checks. ------------------------------------------------
    completeness_ok = len(missing_ids) == 0
    all_metrics_finite = bool(risk_finite and risk.size > 0 and np.all(np.isfinite(risk)))
    minimum_sealed = int(config.decision.minimum_sealed_perturbations)
    # Registered reliability precondition: all risks finite AND every
    # self-distance floor finite/positive.
    reliability_precondition = bool(reliability_ok and all_metrics_finite)
    # The seal opened exactly once (this stage owns the single call).
    leakage_ok = store.sealed_access_count == 1

    # --- Provenance (carry-forward fix a): REAL ledger hash verification. ----
    # The full config digest (fix c) is threaded from the CLI; pure unit tests
    # fall back to run_id so existing direct callers keep working.
    cfg_digest = config_sha256 if config_sha256 is not None else config.config_digest
    expected_checksums = {
        "config": cfg_digest,
        "split_manifest": manifest.checksum,
        "feature_bank": feature_bank.checksum,
        "base_artifact": base_artifact.checksum,
        "method_lock": method_lock.checksum,
        "conformal_artifact": conformal_artifact.checksum,
    }
    provenance_ok = verify_provenance(ledger, expected_checksums, store=store, run_id=run_id)

    # --- P0-1(c): optional config↔feature-bank encoder cross-check. ----------
    # When require_encoder_match=True (set by the CLI for scientific runs),
    # derive the expected primary string from the feature bank's provenance and
    # compare it to config.perturbation_features.primary.  A mismatch means the
    # feature bank was built with the wrong encoder and the evaluation is invalid.
    # Canonical mapping: f"{prov.model_revision}_{prov.pooling}_pool"
    encoder_matches: bool | None = None
    if require_encoder_match:
        prov = feature_bank.provenance
        derived = f"{prov.model_revision}_{prov.pooling}_pool"
        encoder_matches = derived == config.perturbation_features.primary
        if not encoder_matches:
            provenance_ok = False

    evidence: dict = {
        "sealed_ids": list(sealed_ids),
        "missing_ids": list(missing_ids),
        "completeness_ok": completeness_ok,
        "reliability_floors_finite_positive": reliability_ok,
        "sealed_access_count": int(store.sealed_access_count),
    }
    if encoder_matches is not None:
        evidence["encoder_matches_config"] = encoder_matches

    integrity = IntegrityReport(
        provenance_ok=bool(provenance_ok),
        leakage_ok=bool(leakage_ok),
        sealed_n=sealed_n,
        minimum_sealed=minimum_sealed,
        all_metrics_finite=all_metrics_finite and completeness_ok,
        reliability_ok=reliability_precondition,
        evidence=evidence,
    )

    # --- 6, 7, 8. Build verdict (handling the degenerate / invalid branch). --
    # When integrity is invalid (e.g. sealed_n below minimum, or non-finite
    # metrics) we may not be able to run confirmatory/conformal safely.  In that
    # case we synthesise a failed confirmatory result and let compute_verdict
    # return INVALID_EVALUATION — never silently dropped.
    confirmatory_payload: dict | None = None
    rc_curve: dict | None = None
    if integrity.is_valid:
        norm = normalize_by_mean(risk)
        confirmatory = confirmatory_inference(
            norm,
            method_scores,
            comparators=list(COMPARATOR_NAMES),
            augrc_margin=config.inference.secondary_augrc_noninferiority_margin,
            family_confidence=config.inference.family_confidence,
            n_replicates=config.inference.bootstrap_replicates,
            seed=config.manifest_seed,
        )
        n_covered = int(np.count_nonzero(risk <= conformal_artifact.error_bound))
        conformal_passes = conformal_coverage_passes(
            n_covered,
            conformal_artifact.n_cal,
            conformal_artifact.alpha,
            n_test=sealed_n,
        )
        cov_report = coverage_report(
            risk,
            sealed_gate_scores,
            error_bound=conformal_artifact.error_bound,
            threshold=conformal_artifact.predict_threshold,
        )
        # Persist the data the CONFIRMATORY report renders (no recompute later).
        coverage_arr, selective_risk_arr = risk_coverage_curve(norm, sealed_gate_scores)
        rc_curve = {
            "coverage": [float(x) for x in coverage_arr],
            "selective_risk": [float(x) for x in selective_risk_arr],
        }
        confirmatory_payload = _confirmatory_to_jsonable(confirmatory)
    else:
        confirmatory = _FailedConfirmatory()
        conformal_passes = False
        cov_report = {"skipped": "integrity invalid"}

    verdict = compute_verdict(
        integrity,
        conformal_passes,
        confirmatory,
        selected_feature_weight=method_lock.selected_params["gate"]["w"],
    )

    # --- 9. Write the immutable result + ledger (always; never dropped). -----
    if result_path is not None:
        result_path = Path(result_path)
        verdict.write(result_path)
        # Co-locate the audit sidecar: everything the report renders without
        # recomputing the verdict (coverage report, confirmatory bounds,
        # risk-coverage curve arrays, reliability floors, sealed-access audit).
        sidecar = {
            "verdict": verdict.verdict.value,
            "verdict_checksum": verdict.checksum,
            "provenance_ok": bool(provenance_ok),
            "integrity_valid": bool(integrity.is_valid),
            "conformal_passes": bool(conformal_passes),
            "coverage_report": _jsonable(cov_report),
            "confirmatory": _jsonable(confirmatory_payload),
            "risk_coverage_curve": _jsonable(rc_curve),
            "reliability_floors": [_jsonable(f) for f in reliability_floors],
            "self_distance_floor_min": (
                _jsonable(float(min(reliability_floors))) if reliability_floors else None
            ),
            "conformal_artifact_checksum": conformal_artifact.checksum,
            "method_lock_checksum": method_lock.checksum,
            "base_artifact_checksum": base_artifact.checksum,
            "sealed_access_count": int(store.sealed_access_count),
            "sealed_ids": list(sealed_ids),
            "run_id": run_id,
        }
        result_path.with_suffix(".audit.json").write_text(
            json.dumps(sidecar, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
    if ledger is not None:
        # Earlier CLI stages may already have recorded the artifact checksums for
        # provenance verification; record each only if not already present.
        for name, checksum in (
            ("result", verdict.checksum),
            ("conformal_artifact", conformal_artifact.checksum),
            ("method_lock", method_lock.checksum),
            ("base_artifact", base_artifact.checksum),
        ):
            if not _ledger_has(ledger, name):
                ledger.record_artifact(name, checksum)

    return verdict


# ---------------------------------------------------------------------------
# Minimal stand-in confirmatory result for the integrity-invalid branch.
# ---------------------------------------------------------------------------


def _ledger_has(ledger: "RunLedger", name: str) -> bool:
    """Return True if *name* is already recorded in *ledger* (no exception)."""
    from alive.provenance import LedgerError

    try:
        ledger.artifact_sha(name)
        return True
    except LedgerError:
        return False


def _confirmatory_to_jsonable(confirmatory: "ConfirmatoryInference") -> dict:
    """Serialise a :class:`ConfirmatoryInference` to a JSON-safe dict for the report.

    Captures the simultaneous AURC lower bounds, AUGRC degradation upper bounds,
    the added-value delta + bound, and the family/pass-fail flags so the
    confirmatory report can render them WITHOUT recomputing inference.
    """
    return {
        "aurc_point_delta": _jsonable(dict(confirmatory.aurc_point_delta)),
        "aurc_lower_bound": _jsonable(dict(confirmatory.aurc_lower_bound)),
        "aurc_family_passes": bool(confirmatory.aurc_family_passes),
        "augrc_degradation_upper": _jsonable(dict(confirmatory.augrc_degradation_upper)),
        "augrc_margin": _jsonable(float(confirmatory.augrc_margin)),
        "augrc_no_material_degradation": bool(confirmatory.augrc_no_material_degradation),
        "delta_added_value": _jsonable(float(confirmatory.delta_added_value)),
        "delta_added_value_lower_bound": _jsonable(
            float(confirmatory.delta_added_value_lower_bound)
        ),
        "added_value_passes": bool(confirmatory.added_value_passes),
        "family_confidence": _jsonable(float(confirmatory.family_confidence)),
    }


def _jsonable(obj: object) -> object:
    """Recursively coerce a dict/list/scalar to a JSON-safe form (NaN→null)."""
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return f if np.isfinite(f) else None
    if isinstance(obj, (int, str, bool, type(None))):
        return obj
    return repr(obj)


@dataclass(frozen=True)
class _FailedConfirmatory:
    """A confirmatory result with every gate clause failed.

    Used only when integrity is invalid (so the real bootstrap is skipped).
    ``compute_verdict`` will return ``INVALID_EVALUATION`` regardless because the
    integrity gate fires first, but a complete object keeps the clauses auditable.
    """

    aurc_family_passes: bool = False
    augrc_no_material_degradation: bool = False
    added_value_passes: bool = False
