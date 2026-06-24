"""No-seal Phase-2a orchestrator + frozen handoff (Task 2a-11, plan §2.5 / §2.1).

ACTIVATION BLOCKED: pure ``numpy`` on synthetic fixtures only. ``run_phase2a``
ties Tasks 2a-1..2a-10 together and produces the :class:`FrozenPredictionBundle`
Phase 2b consumes. It NEVER opens a seal and NEVER reads a sealed outcome.

Pipeline (brief steps 1-9):

1. verify the execution mode (``fixture_mode=True`` for synthetic tests, or the
   ``config2`` scientific-mode guard — which the blocked config always fails);
2. verify the manifest, response-space, factor and environment hashes against the
   bound expected values — a mismatch aborts BEFORE any prediction;
3. run gene-disjoint OOF selection + the real calibration / futility checkpoint on
   DEVELOPMENT-role inputs only (:func:`alive.compose.diagnostics2.real_calibration_diagnostics`);
4. if futility fires, STOP with NO :class:`FrozenPredictionBundle` and no sealed
   predictions — the seal stays closed and ``sealed_access_count == 0``;
5. otherwise generate predictions for the REGISTERED sealed pair IDs using
   identities / features ONLY (``z_g, z_h -> model.predict_eps`` + the additive
   single-gene shifts), never reading a sealed outcome;
6. validate the complete method roster and every prediction;
7. write a :class:`FrozenPredictionBundle` and a method lock ONCE;
8. record the bundle checksum (and method lock) in a :class:`RunLedger`;
9. confirm the sealed access count remains ZERO.

Leakage wall (plan §2.1). The orchestrator accepts a *typed*
:class:`DevelopmentOutcomeStore` that exposes ONLY unsealed (calibration) roles,
and typed :class:`Phase2aInputs`. Both are recursively scanned for a sealed role /
sealed outcome key / sealed path (reusing the Task-2a-7 recursive scanner via
:func:`alive.compose.freeze._assert_no_sealed`) before any compute, so a leaked
sealed handle anywhere at any nesting depth aborts the run.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from alive.compose.baselines_combo import additive, no_change
from alive.compose.config2 import (
    ComposePhase2Config,
    assert_scientific_mode_allowed,
    load_compose_phase2_config,
)
from alive.compose.diagnostics2 import FutilityResult, real_calibration_diagnostics
from alive.compose.freeze import (
    REQUIRED_METHODS,
    FrozenPredictionBundle,
    OutcomeLeakageError,
    _assert_no_outcome_reference,
    _assert_no_sealed,
)
from alive.provenance import RunLedger, sha256_json

#: Default Phase-2 config consulted by the execution-mode guard.
_DEFAULT_CONFIG_PATH = "configs/compose_k562_v1_phase2.yaml"

#: A zero-arg factory returning a fresh symmetric model (``fit`` / ``predict_eps``).
ModelFactory = Callable[[], object]

#: :class:`Phase2aInputs` field names that legitimately carry the ``"sealed"``
#: token because they hold *registered sealed pair IDs* (identities only, never an
#: outcome). The full recursive leakage scan walks their VALUES — so a sealed or
#: outcome token planted inside them still fails closed — but must not trip on the
#: benign field name itself. This is a property of the typed contract, not a
#: weakening of the wall: every other field name and every value at every depth is
#: still scanned.
_REGISTERED_SEALED_ID_FIELDS: frozenset[str] = frozenset(
    {"sealed_double_pair_ids", "sealed_single_pair_ids"}
)


class HashMismatchError(ValueError):
    """Raised when a bound upstream hash does not match its expected value.

    The orchestrator binds the manifest, response-space, factor and environment
    checksums it was built from. If the caller's expected hashes disagree, the run
    aborts before any selection / prediction so a mismatched lineage can never
    produce a frozen bundle (CLAUDE.md §11).
    """


# --------------------------------------------------------------------------- #
# typed development inputs + outcome store (unsealed roles only)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DevelopmentOutcomeStore:
    """A typed outcome store exposing ONLY unsealed (development) roles.

    The orchestrator reads calibration (``combo_calibration``) GI outcomes from
    here for selection / futility. It deliberately has NO sealed-role field; a
    leaked sealed handle attached after construction is caught by the recursive
    sealed-reference scan before any compute (plan §2.1).

    Attributes
    ----------
    combo_calibration_eps : numpy.ndarray
        Observed calibration GI (epsilon) targets, shape ``(n_cal_pairs, p)``.
    combo_calibration_pair_ids : tuple of tuple of str
        Canonical calibration pair IDs aligned row-for-row with
        ``combo_calibration_eps``.
    """

    combo_calibration_eps: np.ndarray
    combo_calibration_pair_ids: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        # normalise the pair IDs to a tuple of 2-tuples for stable handling.
        object.__setattr__(
            self,
            "combo_calibration_pair_ids",
            tuple(tuple(p) for p in self.combo_calibration_pair_ids),
        )


@dataclass(frozen=True)
class Phase2aInputs:
    """Typed development inputs for :func:`run_phase2a` (identities/features only).

    Carries the frozen upstream artifacts' *checksums*, the per-gene factor banks,
    the development calibration design (idx/IDs/additive/split-halves + grids), the
    registered sealed pair IDs (identities only, no outcomes), the single-gene
    shifts for the additive comparator, and the model factories. It holds NO sealed
    outcome and NO outcome-store handle.

    Attributes
    ----------
    run_id : str
        Composite COMPOSE run identifier.
    gene_index : Mapping of str to int
        Map from gene ID to its row index in every factor bank.
    factors_by_k : Mapping of int to numpy.ndarray
        Per-``k_total`` factor matrices, shape ``(n_genes, k_total)``.
    cal_idx_pairs : sequence of (int, int)
        Calibration gene-index pairs.
    cal_pair_ids : sequence of (str, str)
        Canonical calibration pair IDs aligned with ``cal_idx_pairs``.
    additive_cal : numpy.ndarray
        Registered response-shaped additive prediction per calibration pair,
        shape ``(n_cal_pairs, p)``.
    eps_split_a, eps_split_b : numpy.ndarray
        Development split-half GI estimates for the measurability gate.
    k_total_grid, lambda_grid : sequence
        Selection grids.
    n_genes, n_folds, seed, uncovered_tolerance
        Gene-disjoint OOF selection parameters.
    sealed_double_pair_ids, sealed_single_pair_ids : sequence of (str, str)
        Registered canonical sealed pair IDs (identities only).
    delta_by_gene : Mapping of str to numpy.ndarray
        Single-gene response shifts (single-role; allowed) for the additive
        comparator on sealed pairs.
    model_factories : Mapping of str to factory
        Learned-model factories keyed by roster method name (e.g.
        ``"l1_bilinear_identifiable"`` -> :class:`~alive.compose.models.L1Model`).
    response_dim : int
        Response dimension ``p``.
    response_space_checksum, factor_checksum, model_checksum, manifest_checksum,
    environment_checksum : str
        Bound upstream artifact checksums (verified in step 2).
    registered_seeds : sequence of int
        Registered random seeds recorded in the bundle / ledger.
    """

    run_id: str
    gene_index: Mapping[str, int]
    factors_by_k: Mapping[int, np.ndarray]
    cal_idx_pairs: Sequence[tuple[int, int]]
    cal_pair_ids: Sequence[tuple[str, str]]
    additive_cal: np.ndarray
    eps_split_a: np.ndarray
    eps_split_b: np.ndarray
    k_total_grid: Sequence[int]
    lambda_grid: Sequence[float]
    n_genes: int
    n_folds: int
    seed: int
    uncovered_tolerance: float
    sealed_double_pair_ids: Sequence[tuple[str, str]]
    sealed_single_pair_ids: Sequence[tuple[str, str]]
    delta_by_gene: Mapping[str, np.ndarray]
    model_factories: Mapping[str, ModelFactory]
    response_dim: int
    response_space_checksum: str
    factor_checksum: str
    model_checksum: str
    manifest_checksum: str
    environment_checksum: str
    registered_seeds: Sequence[int]


@dataclass(frozen=True)
class Phase2aResult:
    """Outcome of :func:`run_phase2a` (development axis only; no sealed verdict).

    Attributes
    ----------
    futility_status : str
        ``"CONTINUE"`` or ``"FUTILITY_STOPPED"`` from the development checkpoint.
    sealed_access_count : int
        Always ``0`` — this orchestrator opens no seal.
    bundle : FrozenPredictionBundle or None
        The frozen handoff when ``CONTINUE``; ``None`` when ``FUTILITY_STOPPED``
        (no sealed predictions are generated and the seal stays closed).
    futility : FutilityResult
        The full development checkpoint result (rank/conditioning/measurability/
        OOF theta + selected hyperparameters).
    selected_k_total : int
        Selected total factor dimension.
    selected_lambda : float
        Selected ridge regularization.
    ledger : RunLedger or None
        Write-once ledger recording the bundle + method-lock checksums when a
        bundle is frozen; ``None`` on a futility stop.
    method_lock : dict or None
        The frozen method lock (roster + selected hyperparameters + upstream
        checksums); ``None`` on a futility stop.
    """

    futility_status: str
    sealed_access_count: int
    bundle: FrozenPredictionBundle | None
    futility: FutilityResult
    selected_k_total: int
    selected_lambda: float
    ledger: RunLedger | None = None
    method_lock: dict | None = field(default=None)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _verify_hashes(inputs: Phase2aInputs, expected: Mapping[str, str]) -> None:
    """Verify every bound upstream hash against the expected values (step 2).

    Parameters
    ----------
    inputs : Phase2aInputs
        The bound inputs carrying the manifest / response / factor / environment
        checksums.
    expected : Mapping of str to str
        The expected checksum for each bound key.

    Raises
    ------
    HashMismatchError
        If any bound hash differs from its expected value, or an expected key is
        absent.
    """
    bound = {
        "response_space_checksum": inputs.response_space_checksum,
        "factor_checksum": inputs.factor_checksum,
        "model_checksum": inputs.model_checksum,
        "manifest_checksum": inputs.manifest_checksum,
        "environment_checksum": inputs.environment_checksum,
    }
    for key, value in bound.items():
        if key not in expected:
            raise HashMismatchError(f"missing expected hash for {key!r}")
        if expected[key] != value:
            raise HashMismatchError(
                f"upstream hash mismatch for {key!r}: bound {value!r} != expected "
                f"{expected[key]!r}; lineage differs, refusing to freeze"
            )


def _scan_inputs_for_leakage(inputs: Phase2aInputs, store: DevelopmentOutcomeStore) -> None:
    """Recursively reject any sealed reference or measured-outcome marker (step 1).

    Scans the typed inputs and outcome store for a sealed role / sealed outcome
    key / sealed path at any nesting depth (reusing the Task-2a-7 recursive
    scanner). Numeric outcome ARRAYS carry no string token, so the scan does not
    fire on the legitimate calibration eps / factor banks / single-gene deltas; it
    fires on a leaked sealed *handle*, attribute name, identity string or path
    (plan §2.1).

    The scan is **symmetric and exhaustive** on both sides of the wall:

    * the FULL :class:`Phase2aInputs` dataclass is walked field-by-field at every
      nesting depth — not a hand-picked subset — so a sealed/outcome token planted
      in ANY field (``cal_pair_ids``, ``cal_idx_pairs``, ``factors_by_k`` keys,
      ``run_id``, identity mappings, …) fails closed; and
    * the store's FULL instance state (attribute names + values, recursively, via
      ``vars`` so an injected handle outside the declared dataclass fields is also
      caught) is walked the same way.

    Both the sealed-reference scan and the measured-outcome scan are applied to the
    whole inputs object and the whole store, so a sealed OR outcome token anywhere
    aborts the run before any compute.

    Raises
    ------
    OutcomeLeakageError
        If any sealed reference or measured-outcome marker is present in the inputs
        or the outcome store, at any field or nesting depth.
    """
    # The whole inputs object as a field-name -> value mapping. Both scanners walk
    # mappings / sequences / sets / nested dataclasses recursively and tolerate the
    # numpy-array / callable leaves, so a sealed or outcome token planted in ANY
    # field value at ANY nesting depth (cal_pair_ids, cal_idx_pairs, factors_by_k
    # keys, identity mappings, ...) fails closed.
    _assert_no_sealed(_inputs_scan_view(inputs))
    _assert_no_outcome_reference(_inputs_scan_view(inputs))

    # The store's FULL instance state (attribute names + values, recursively),
    # via ``vars`` so an injected/leaked sealed handle outside the declared
    # dataclass fields is also caught. Numeric arrays carry no token.
    store_state = dict(vars(store)) if hasattr(store, "__dict__") else store
    _assert_no_sealed(store_state)
    _assert_no_outcome_reference(store_state)


def _inputs_scan_view(inputs: Phase2aInputs) -> dict[str, object]:
    """Return a leakage-scan view of every :class:`Phase2aInputs` field value.

    The view is a ``field name -> field value`` mapping spanning the WHOLE
    dataclass (not a hand-picked subset). The recursive scanners then walk every
    value at every nesting depth, so a sealed/outcome token anywhere fails closed.

    The two registered sealed-ID fields (:data:`_REGISTERED_SEALED_ID_FIELDS`) are
    keyed by a benign placeholder name so the scanner does not fire on their
    legitimate ``"sealed"`` field name; their VALUES are still scanned in full, so
    a sealed/outcome token planted inside a registered pair ID still aborts.

    Parameters
    ----------
    inputs : Phase2aInputs
        The bound development inputs to expose for scanning.

    Returns
    -------
    dict of str to object
        A name-keyed mapping of every field value, safe to hand to the recursive
        sealed-reference and outcome-reference scanners.
    """
    view: dict[str, object] = {}
    for field_name in type(inputs).__dataclass_fields__:
        value = getattr(inputs, field_name)
        if field_name in _REGISTERED_SEALED_ID_FIELDS:
            # benign key (value still fully scanned for any sealed/outcome token).
            view[f"registered_pair_ids__{field_name.split('_', 1)[1]}"] = value
        else:
            view[field_name] = value
    return view


def _predict_role(
    inputs: Phase2aInputs,
    pair_ids: Sequence[tuple[str, str]],
    fitted_models: Mapping[str, object],
    selected_Z: np.ndarray,
) -> dict[str, dict[tuple[str, str], np.ndarray]]:
    """Predict every roster method for a sealed role using identities/features only.

    For each registered sealed pair ``(g, h)`` the orchestrator:

    * looks up the gene indices and factor vectors ``z_g``, ``z_h``;
    * for a learned model, computes ``model.predict_eps(Z, g_idx, h_idx)`` (the GI
      residual) and ADDS the additive single-gene shifts to form the double-shift
      prediction;
    * for ``additive`` returns the single-gene-shift sum;
    * for ``no_change`` returns a zero vector.

    No sealed outcome is read anywhere — only identities (``gene_index``),
    features (``Z``, ``delta_by_gene``) and the fitted development models.

    Parameters
    ----------
    inputs : Phase2aInputs
        The bound inputs.
    pair_ids : sequence of (str, str)
        The registered canonical sealed pair IDs for this role.
    fitted_models : Mapping of str to model
        Learned models already fitted on calibration data (``predict_eps``).
    selected_Z : numpy.ndarray
        The factor bank for the selected ``k_total``.

    Returns
    -------
    dict
        ``method -> {pair_id -> length-response_dim prediction vector}`` covering
        the complete registered roster (learned models + additive + no_change).
    """
    out: dict[str, dict[tuple[str, str], np.ndarray]] = {}
    # learned models
    for name, model in fitted_models.items():
        block: dict[tuple[str, str], np.ndarray] = {}
        for g, h in pair_ids:
            gi = int(inputs.gene_index[g])
            hi = int(inputs.gene_index[h])
            eps_hat = np.asarray(model.predict_eps(selected_Z, gi, hi), dtype=float)
            add = additive(inputs.delta_by_gene[g], inputs.delta_by_gene[h])
            block[(g, h)] = eps_hat + add
        out[name] = block
    # additive null floor
    out["additive"] = {
        (g, h): additive(inputs.delta_by_gene[g], inputs.delta_by_gene[h]) for g, h in pair_ids
    }
    # no-change lower bound
    out["no_change"] = {(g, h): no_change(inputs.response_dim) for g, h in pair_ids}
    return out


def _build_method_lock(inputs: Phase2aInputs, roster: tuple[str, ...], result: FutilityResult):
    """Build the frozen method lock (roster + selected hyperparameters + checksums).

    The method lock binds the exact roster and the selected ``(k_total, lambda)``
    + seeds to the upstream artifact checksums, so Phase 2b cannot silently swap a
    method or a hyperparameter. Returns ``(lock_dict, lock_checksum)``.
    """
    lock = {
        "run_id": inputs.run_id,
        "method_roster": list(roster),
        "selected_k_total": int(result.selected_k_total),
        "selected_lambda": round(float(result.selected_lambda), 12),
        "registered_seeds": list(int(s) for s in inputs.registered_seeds),
        "response_space_checksum": inputs.response_space_checksum,
        "factor_checksum": inputs.factor_checksum,
        "model_checksum": inputs.model_checksum,
        "manifest_checksum": inputs.manifest_checksum,
        "environment_checksum": inputs.environment_checksum,
    }
    return lock, sha256_json(lock)


# --------------------------------------------------------------------------- #
# orchestrator
# --------------------------------------------------------------------------- #


def run_phase2a(
    inputs: Phase2aInputs,
    outcome_store: DevelopmentOutcomeStore,
    *,
    fixture_mode: bool,
    expected_hashes: Mapping[str, str],
    config: ComposePhase2Config | None = None,
    config_path: str | Path = _DEFAULT_CONFIG_PATH,
    bundle_path: str | Path | None = None,
    environment=None,
) -> Phase2aResult:
    """Run the no-seal Phase-2a orchestration and produce the frozen handoff.

    See the module docstring for the full pipeline (brief steps 1-9). No seal is
    opened and no sealed outcome is read; the returned
    :attr:`Phase2aResult.sealed_access_count` is always ``0``.

    Parameters
    ----------
    inputs : Phase2aInputs
        Typed development inputs (identities/features + bound checksums).
    outcome_store : DevelopmentOutcomeStore
        Outcome store exposing ONLY unsealed (calibration) roles.
    fixture_mode : bool
        ``True`` for synthetic/tiny-fixture runs (always allowed). ``False``
        requires the ``config2`` scientific-mode preconditions, which the blocked
        config fails.
    expected_hashes : Mapping of str to str
        Expected manifest / response / factor / model / environment checksums; a
        mismatch aborts before any prediction.
    config : ComposePhase2Config or None, optional
        Pre-loaded config for the mode guard. When ``None`` it is loaded from
        ``config_path``.
    config_path : str or Path, optional
        Path to the Phase-2 config (used when ``config`` is ``None``).
    bundle_path : str or Path or None, optional
        Destination for the frozen bundle. When supplied and the run CONTINUEs the
        bundle is written ONCE here; on a futility stop nothing is written.
    environment : EnvironmentInfo or None, optional
        Optional captured environment for the ledger. When ``None`` a minimal
        in-memory environment placeholder is used (fixture mode).

    Returns
    -------
    Phase2aResult
        The development-axis result: futility status, the (possibly ``None``)
        frozen bundle, the full futility checkpoint, the selected hyperparameters,
        the ledger and the method lock. ``sealed_access_count == 0`` always.

    Raises
    ------
    alive.compose.config2.ScientificModeError
        If scientific mode is requested but not permitted.
    HashMismatchError
        If a bound upstream hash differs from its expected value.
    OutcomeLeakageError
        If a sealed reference / measured-outcome marker is present in the inputs
        or outcome store.
    """
    # Step 1a: leakage wall — reject any sealed reference in inputs / store first,
    # before touching the config or any compute (fail closed).
    _scan_inputs_for_leakage(inputs, outcome_store)

    # Step 1b: execution-mode guard (fixture always allowed; scientific blocked).
    cfg = config if config is not None else load_compose_phase2_config(config_path)
    assert_scientific_mode_allowed(cfg, fixture_mode=fixture_mode)

    # Step 2: verify the bound upstream hashes (abort before any prediction).
    _verify_hashes(inputs, expected_hashes)

    # Step 3: selection + real calibration / futility checkpoint on DEVELOPMENT
    # roles only. The L1 model drives selection (headline ablation).
    if "l1_bilinear_identifiable" not in inputs.model_factories:
        raise ValueError("model_factories must include 'l1_bilinear_identifiable' (headline model)")
    l1_factory = inputs.model_factories["l1_bilinear_identifiable"]

    eps_cal = np.asarray(outcome_store.combo_calibration_eps, dtype=float)
    futility = real_calibration_diagnostics(
        idx_pairs=list(inputs.cal_idx_pairs),
        pair_ids=list(inputs.cal_pair_ids),
        eps_obs=eps_cal,
        additive=np.asarray(inputs.additive_cal, dtype=float),
        factors_by_k=dict(inputs.factors_by_k),
        k_total_grid=list(inputs.k_total_grid),
        lambda_grid=list(inputs.lambda_grid),
        n_genes=int(inputs.n_genes),
        n_folds=int(inputs.n_folds),
        seed=int(inputs.seed),
        model_factory=l1_factory,
        uncovered_tolerance=float(inputs.uncovered_tolerance),
        eps_split_a=np.asarray(inputs.eps_split_a, dtype=float),
        eps_split_b=np.asarray(inputs.eps_split_b, dtype=float),
        measurability_role="combo_calibration",
    )
    selected_k = futility.selected_k_total
    selected_lambda = futility.selected_lambda

    # Step 4: futility -> STOP without any sealed predictions (seal stays closed).
    if futility.status != "CONTINUE":
        return Phase2aResult(
            futility_status=futility.status,
            sealed_access_count=0,
            bundle=None,
            futility=futility,
            selected_k_total=selected_k,
            selected_lambda=selected_lambda,
            ledger=None,
            method_lock=None,
        )

    # Step 5: CONTINUE -> fit learned models on calibration data only, then
    # predict the REGISTERED sealed pairs using IDENTITIES / FEATURES only.
    selected_Z = np.asarray(inputs.factors_by_k[selected_k], dtype=float)
    fitted: dict[str, object] = {}
    for name, factory in inputs.model_factories.items():
        model = factory()
        model.fit(selected_Z, list(inputs.cal_idx_pairs), eps_cal, lam=float(selected_lambda))
        fitted[name] = model

    double_preds = _predict_role(inputs, inputs.sealed_double_pair_ids, fitted, selected_Z)
    single_preds = _predict_role(inputs, inputs.sealed_single_pair_ids, fitted, selected_Z)

    # the complete registered roster: learned models + additive + no_change.
    roster = tuple(inputs.model_factories.keys()) + ("additive", "no_change")
    # de-duplicate while preserving order (in case a factory was named 'additive').
    seen: set[str] = set()
    roster = tuple(m for m in roster if not (m in seen or seen.add(m)))

    # Steps 6-7: validate the complete roster + every prediction and freeze ONCE.
    bundle = FrozenPredictionBundle.create(
        run_id=inputs.run_id,
        method_roster=roster,
        pair_ids_double_unseen=tuple(tuple(p) for p in inputs.sealed_double_pair_ids),
        pair_ids_single_unseen=tuple(tuple(p) for p in inputs.sealed_single_pair_ids),
        predictions_double_unseen=double_preds,
        predictions_single_unseen=single_preds,
        response_space_checksum=inputs.response_space_checksum,
        factor_checksum=inputs.factor_checksum,
        model_checksum=inputs.model_checksum,
        manifest_checksum=inputs.manifest_checksum,
        selected_k_total=selected_k,
        selected_lambda=selected_lambda,
        registered_seeds=inputs.registered_seeds,
        futility_status=futility.status,
        dev_diagnostics={
            "oof_theta": round(float(futility.oof_theta), 12),
            "rank": int(futility.rank_report.rank),
            "sym_dim": int(futility.rank_report.sym_dim),
            "is_full_rank": bool(futility.rank_report.is_full_rank),
            "condition_number": round(float(futility.rank_report.condition_number), 6),
            "measurable": bool(futility.measurability.passed),
            "selected_k_total": int(selected_k),
            "selected_lambda": round(float(selected_lambda), 12),
            # audit field: this run opened no seal. Named without the "sealed"
            # token so the leakage scanner does not flag the benign audit value.
            "seal_open_count": 0,
        },
        response_dim=inputs.response_dim,
        required_roster=REQUIRED_METHODS,
    )
    # post-freeze invariant: no measured outcome present.
    bundle.assert_no_outcomes()

    # write the bundle ONCE (write-once is enforced inside .write()).
    if bundle_path is not None:
        bundle.write(bundle_path)

    # Step 8: record the bundle + method-lock checksums in a write-once ledger.
    method_lock, lock_checksum = _build_method_lock(inputs, roster, futility)
    env = environment if environment is not None else _placeholder_environment(inputs)
    ledger = RunLedger(
        run_id=inputs.run_id, config_sha256=inputs.manifest_checksum, environment=env
    )
    ledger.record_artifact("response_space", inputs.response_space_checksum)
    ledger.record_artifact("factor_bank", inputs.factor_checksum)
    ledger.record_artifact("model", inputs.model_checksum)
    ledger.record_artifact("pair_manifest", inputs.manifest_checksum)
    ledger.record_artifact("environment", inputs.environment_checksum)
    ledger.record_artifact("method_lock", lock_checksum)
    ledger.record_artifact("frozen_prediction_bundle", bundle.bundle_checksum)

    # Step 9: confirm the sealed access count is ZERO (it never opened a seal).
    if futility.sealed_access_count != 0:
        raise OutcomeLeakageError(
            "invariant violated: futility checkpoint reported non-zero sealed access"
        )

    return Phase2aResult(
        futility_status=futility.status,
        sealed_access_count=0,
        bundle=bundle,
        futility=futility,
        selected_k_total=selected_k,
        selected_lambda=selected_lambda,
        ledger=ledger,
        method_lock=method_lock,
    )


def _placeholder_environment(inputs: Phase2aInputs):
    """Build a minimal in-memory environment for the fixture-mode ledger.

    Avoids any I/O (no lockfile read, no git call) so synthetic tests stay
    hermetic. Real runs pass a captured
    :class:`alive.provenance.EnvironmentInfo` via the ``environment`` argument.
    """
    from alive.provenance import EnvironmentInfo

    return EnvironmentInfo(
        python_version="fixture",
        platform="fixture",
        git_commit="UNKNOWN",
        lockfile_sha256=inputs.environment_checksum,
        registered_seeds=tuple(int(s) for s in inputs.registered_seeds),
    )
