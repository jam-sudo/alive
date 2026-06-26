"""No-seal Phase-2a orchestrator + frozen handoff (Task 2a-11, plan §2.5 / §2.1).

ACTIVATION BLOCKED: pure ``numpy`` on synthetic fixtures only. ``run_phase2a``
ties Tasks 2a-1..2a-10 together and produces the :class:`FrozenPredictionBundle`
Phase 2b consumes. It NEVER opens a seal and NEVER reads a sealed outcome.

Pipeline (brief steps 1-9):

1. enter through either the bounded fixture-only API or the scientific API,
   whose activation guard the blocked config always fails;
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

from alive.compose.baselines_combo import additive, no_change, perturbation_mean
from alive.compose.config2 import (
    ActivationRecord,
    ComposePhase2Config,
    ScientificModeError,
    assert_scientific_mode_allowed,
    load_compose_phase2_config,
)
from alive.compose.datacard import compute_compose_run_id
from alive.compose.diagnostics2 import FutilityResult, real_calibration_diagnostics
from alive.compose.freeze import (
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


@dataclass(frozen=True)
class OutcomeAccessAudit:
    """Manifest-bound proof that only the calibration role was materialised."""

    role: str
    manifest_checksum: str
    source_checksum: str
    sealed_access_count: int
    source_kind: str


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
    access_audit: OutcomeAccessAudit
    content_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        # normalise the pair IDs to a tuple of 2-tuples for stable handling.
        object.__setattr__(
            self,
            "combo_calibration_pair_ids",
            tuple(tuple(p) for p in self.combo_calibration_pair_ids),
        )
        eps = np.asarray(self.combo_calibration_eps, dtype=float)
        if eps.ndim != 2 or eps.shape[0] != len(self.combo_calibration_pair_ids):
            raise ValueError(
                "combo_calibration_eps must be a 2-D array aligned row-for-row "
                "with combo_calibration_pair_ids"
            )
        if not np.all(np.isfinite(eps)):
            raise ValueError("combo_calibration_eps contains non-finite values")
        if self.access_audit.role != "combo_calibration":
            raise OutcomeLeakageError(
                f"development outcome audit role must be 'combo_calibration', "
                f"got {self.access_audit.role!r}"
            )
        if self.access_audit.sealed_access_count != 0:
            raise OutcomeLeakageError(
                "development outcome store reports a non-zero sealed access count"
            )
        if self.access_audit.source_kind not in {"synthetic_fixture", "audited_unsealed"}:
            raise ValueError(
                "outcome audit source_kind must be 'synthetic_fixture' or 'audited_unsealed'"
            )
        if not self.access_audit.manifest_checksum or not self.access_audit.source_checksum:
            raise ValueError("outcome access audit checksums must be non-empty")
        object.__setattr__(self, "combo_calibration_eps", eps.copy())
        object.__setattr__(self, "content_checksum", _outcome_store_checksum(self))


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
    data_card_checksum: str
    raw_data_checksum: str
    sequence_mapping_checksum: str
    content_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "content_checksum", _phase2a_inputs_checksum(self))


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


def _array_payload(value: np.ndarray | Sequence) -> list:
    """Return a deterministic JSON-compatible numeric-array payload."""
    return np.asarray(value).tolist()


def _phase2a_inputs_checksum(inputs: Phase2aInputs) -> str:
    """Bind every in-memory Phase-2a input that can affect a frozen bundle."""
    payload = {
        "run_id": inputs.run_id,
        "gene_index": sorted(
            ((str(g), int(i)) for g, i in inputs.gene_index.items()),
            key=lambda item: item[0].encode("utf-8"),
        ),
        "factors_by_k": {
            str(k): _array_payload(inputs.factors_by_k[k])
            for k in sorted(inputs.factors_by_k, key=lambda x: str(x))
        },
        "cal_idx_pairs": [list(p) for p in inputs.cal_idx_pairs],
        "cal_pair_ids": [list(p) for p in inputs.cal_pair_ids],
        "additive_cal": _array_payload(inputs.additive_cal),
        "eps_split_a": _array_payload(inputs.eps_split_a),
        "eps_split_b": _array_payload(inputs.eps_split_b),
        "k_total_grid": [int(x) for x in inputs.k_total_grid],
        "lambda_grid": [float(x) for x in inputs.lambda_grid],
        "n_genes": int(inputs.n_genes),
        "n_folds": int(inputs.n_folds),
        "seed": int(inputs.seed),
        "uncovered_tolerance": float(inputs.uncovered_tolerance),
        "registered_double_pair_ids": [list(p) for p in inputs.sealed_double_pair_ids],
        "registered_single_pair_ids": [list(p) for p in inputs.sealed_single_pair_ids],
        "delta_by_gene": {
            str(g): _array_payload(inputs.delta_by_gene[g])
            for g in sorted(inputs.delta_by_gene, key=lambda x: str(x).encode("utf-8"))
        },
        "model_roster": list(inputs.model_factories),
        "response_dim": int(inputs.response_dim),
        "response_space_checksum": inputs.response_space_checksum,
        "factor_checksum": inputs.factor_checksum,
        "model_checksum": inputs.model_checksum,
        "manifest_checksum": inputs.manifest_checksum,
        "environment_checksum": inputs.environment_checksum,
        "registered_seeds": [int(x) for x in inputs.registered_seeds],
        "data_card_checksum": inputs.data_card_checksum,
        "raw_data_checksum": inputs.raw_data_checksum,
        "sequence_mapping_checksum": inputs.sequence_mapping_checksum,
    }
    return sha256_json(payload)


def _outcome_store_checksum(store: DevelopmentOutcomeStore) -> str:
    """Bind calibration outcomes, their row identities, and access provenance."""
    audit = store.access_audit
    return sha256_json(
        {
            "combo_calibration_eps": _array_payload(store.combo_calibration_eps),
            "combo_calibration_pair_ids": [list(p) for p in store.combo_calibration_pair_ids],
            "access_audit": {
                "role": audit.role,
                "manifest_checksum": audit.manifest_checksum,
                "source_checksum": audit.source_checksum,
                "sealed_access_count": int(audit.sealed_access_count),
                "source_kind": audit.source_kind,
            },
        }
    )


def _verify_hashes(
    inputs: Phase2aInputs,
    outcome_store: DevelopmentOutcomeStore,
    expected: Mapping[str, str],
) -> None:
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
    if _phase2a_inputs_checksum(inputs) != inputs.content_checksum:
        raise HashMismatchError("Phase2aInputs content changed after its checksum was bound")
    if _outcome_store_checksum(outcome_store) != outcome_store.content_checksum:
        raise HashMismatchError("development outcome content changed after its checksum was bound")
    if outcome_store.access_audit.manifest_checksum != inputs.manifest_checksum:
        raise HashMismatchError(
            "development outcome audit manifest does not match the Phase2a pair manifest"
        )


def _validate_config_contract(
    inputs: Phase2aInputs,
    config: ComposePhase2Config,
) -> None:
    """Require runtime selection and roster values to equal the preregistration."""
    mismatches: list[str] = []
    if tuple(int(x) for x in inputs.k_total_grid) != config.total_k_grid:
        mismatches.append("k_total_grid")
    if tuple(float(x) for x in inputs.lambda_grid) != config.lambda_grid:
        mismatches.append("lambda_grid")
    if int(inputs.n_folds) != config.oof_folds:
        mismatches.append("n_folds")
    if float(inputs.uncovered_tolerance) != config.uncovered_tolerance:
        mismatches.append("uncovered_tolerance")
    if int(inputs.seed) != config.split_seed:
        mismatches.append("seed")
    if tuple(int(x) for x in inputs.registered_seeds) != config.registered_seeds:
        mismatches.append("registered_seeds")
    learned_roster = tuple(
        name
        for name in config.method_roster
        if name not in {"additive", "no_change", "perturbation_mean"}
    )
    if tuple(inputs.model_factories) != learned_roster:
        mismatches.append("model_roster")
    if mismatches:
        raise ValueError(
            "runtime inputs differ from the preregistered config: " + ", ".join(mismatches)
        )


def _validate_run_identity(inputs: Phase2aInputs, config: ComposePhase2Config) -> None:
    """Recompute the composite run ID from its registered provenance inputs."""
    expected = compute_compose_run_id(
        config_digest=config.config_sha256,
        data_card_digest=inputs.data_card_checksum,
        raw_or_source_digest=inputs.raw_data_checksum,
        sequence_mapping_digest=inputs.sequence_mapping_checksum,
    )
    if inputs.run_id != expected:
        raise HashMismatchError(
            f"run_id mismatch: supplied {inputs.run_id!r}, recomputed {expected!r}"
        )


def _validate_pair_alignment(
    inputs: Phase2aInputs,
    outcome_store: DevelopmentOutcomeStore,
) -> None:
    """Fail closed unless calibration IDs and all row-aligned arrays agree."""
    input_ids = tuple(tuple(p) for p in inputs.cal_pair_ids)
    if outcome_store.combo_calibration_pair_ids != input_ids:
        raise ValueError(
            "combo_calibration outcome pair IDs are not exactly aligned with cal_pair_ids"
        )
    n = len(input_ids)
    aligned = {
        "cal_idx_pairs": len(inputs.cal_idx_pairs),
        "additive_cal": np.asarray(inputs.additive_cal).shape[0],
        "eps_split_a": np.asarray(inputs.eps_split_a).shape[0],
        "eps_split_b": np.asarray(inputs.eps_split_b).shape[0],
        "combo_calibration_eps": np.asarray(outcome_store.combo_calibration_eps).shape[0],
    }
    bad = {name: count for name, count in aligned.items() if count != n}
    if bad:
        raise ValueError(f"calibration row alignment mismatch: expected {n}, got {bad}")


def _assert_fixture_payload(
    inputs: Phase2aInputs,
    outcome_store: DevelopmentOutcomeStore,
) -> None:
    """Keep the fixture entry point bounded and distinct from scientific data."""
    if outcome_store.access_audit.source_kind != "synthetic_fixture":
        raise ScientificModeError(
            "fixture execution requires an outcome audit with source_kind='synthetic_fixture'"
        )
    if inputs.n_genes > 128 or len(inputs.cal_pair_ids) > 4096 or inputs.response_dim > 256:
        raise ScientificModeError(
            "fixture payload exceeds the synthetic/tiny-fixture safety limits"
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
    store_state = dict(vars(store)) if hasattr(store, "__dict__") else {"store": store}
    audit = store_state.pop("access_audit", None)
    if isinstance(audit, OutcomeAccessAudit):
        # The audit's zero access counter is a required safety signal.  Expose it
        # under a benign name while still scanning every value and all unexpected
        # injected attributes.  ``source_kind`` is a construction-validated
        # two-value enum, not free text: scanning it as a string would false-trip
        # on the legitimate ``audited_unsealed`` value (it contains "sealed"), so
        # surface it as a benign boolean instead — the enum itself is already
        # validated in :meth:`DevelopmentOutcomeStore.__post_init__`.
        store_state["access_audit_record"] = {
            "role": audit.role,
            "manifest_checksum": audit.manifest_checksum,
            "source_checksum": audit.source_checksum,
            "seal_open_count": audit.sealed_access_count,
            "is_synthetic_fixture": audit.source_kind == "synthetic_fixture",
        }
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
    perturbation_mean_prediction: np.ndarray,
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
    out["perturbation_mean"] = {
        (g, h): np.asarray(perturbation_mean_prediction, dtype=float).copy() for g, h in pair_ids
    }
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
    fixture_mode: bool = False,
    expected_hashes: Mapping[str, str],
    config: ComposePhase2Config | None = None,
    config_path: str | Path = _DEFAULT_CONFIG_PATH,
    bundle_path: str | Path | None = None,
    environment=None,
    activation_record: ActivationRecord | None = None,
    git_is_clean: bool | None = None,
) -> Phase2aResult:
    """Run scientific Phase-2a after all activation conditions are satisfied.

    ``fixture_mode=True`` is intentionally rejected here.  Synthetic tests must
    use :func:`run_phase2a_fixture`, so a caller-controlled boolean cannot bypass
    owner activation, clean-Git, and evidence-hash checks.
    """
    if fixture_mode:
        raise ScientificModeError(
            "run_phase2a does not accept fixture_mode=True; use run_phase2a_fixture "
            "with a bounded synthetic outcome audit"
        )
    return _run_phase2a_core(
        inputs,
        outcome_store,
        expected_hashes=expected_hashes,
        config=config,
        config_path=config_path,
        bundle_path=bundle_path,
        environment=environment,
        fixture_execution=False,
        activation_record=activation_record,
        git_is_clean=git_is_clean,
    )


def run_phase2a_fixture(
    inputs: Phase2aInputs,
    outcome_store: DevelopmentOutcomeStore,
    *,
    expected_hashes: Mapping[str, str],
    config: ComposePhase2Config | None = None,
    config_path: str | Path = _DEFAULT_CONFIG_PATH,
    bundle_path: str | Path | None = None,
    environment=None,
) -> Phase2aResult:
    """Run the bounded synthetic/tiny-fixture Phase-2a path."""
    _assert_fixture_payload(inputs, outcome_store)
    return _run_phase2a_core(
        inputs,
        outcome_store,
        expected_hashes=expected_hashes,
        config=config,
        config_path=config_path,
        bundle_path=bundle_path,
        environment=environment,
        fixture_execution=True,
        activation_record=None,
        git_is_clean=None,
    )


def _run_phase2a_core(
    inputs: Phase2aInputs,
    outcome_store: DevelopmentOutcomeStore,
    *,
    expected_hashes: Mapping[str, str],
    config: ComposePhase2Config | None,
    config_path: str | Path,
    bundle_path: str | Path | None,
    environment,
    fixture_execution: bool,
    activation_record: ActivationRecord | None,
    git_is_clean: bool | None,
) -> Phase2aResult:
    """Shared implementation after the public execution boundary is resolved.

    Parameters
    ----------
    inputs : Phase2aInputs
        Typed development inputs (identities/features + bound checksums).
    outcome_store : DevelopmentOutcomeStore
        Outcome store exposing ONLY unsealed (calibration) roles.
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

    # Step 1b: execution-mode guard.  Only this internal core can receive a
    # fixture execution flag; the public scientific entry point rejects it.
    cfg = config if config is not None else load_compose_phase2_config(config_path)
    if not fixture_execution:
        assert_scientific_mode_allowed(
            cfg,
            fixture_mode=False,
            activation_record=activation_record,
            git_is_clean=git_is_clean,
        )
        if outcome_store.access_audit.source_kind != "audited_unsealed":
            raise ScientificModeError(
                "scientific Phase2a requires source_kind='audited_unsealed'; "
                "synthetic fixture outcomes are not scientific evidence"
            )

    # Step 2: bind runtime values, in-memory contents, role provenance and run ID.
    _validate_config_contract(inputs, cfg)
    _verify_hashes(inputs, outcome_store, expected_hashes)
    _validate_pair_alignment(inputs, outcome_store)
    _validate_run_identity(inputs, cfg)

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

    calibration_double_shifts = np.asarray(inputs.additive_cal, dtype=float) + eps_cal
    mean_prediction = perturbation_mean(calibration_double_shifts)
    double_preds = _predict_role(
        inputs,
        inputs.sealed_double_pair_ids,
        fitted,
        selected_Z,
        mean_prediction,
    )
    single_preds = _predict_role(
        inputs,
        inputs.sealed_single_pair_ids,
        fitted,
        selected_Z,
        mean_prediction,
    )

    roster = cfg.method_roster

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
        required_roster=cfg.method_roster,
    )
    # post-freeze invariant: no measured outcome present.
    bundle.assert_no_outcomes()

    # write the bundle ONCE (write-once is enforced inside .write()).
    if bundle_path is not None:
        bundle.write(bundle_path)

    # Step 8: record the bundle + method-lock checksums in a write-once ledger.
    method_lock, lock_checksum = _build_method_lock(inputs, roster, futility)
    env = environment if environment is not None else _placeholder_environment(inputs)
    ledger = RunLedger(run_id=inputs.run_id, config_sha256=cfg.config_sha256, environment=env)
    ledger.record_artifact("data_card", inputs.data_card_checksum)
    ledger.record_artifact("raw_data", inputs.raw_data_checksum)
    ledger.record_artifact("sequence_mapping", inputs.sequence_mapping_checksum)
    ledger.record_artifact("phase2a_inputs", inputs.content_checksum)
    ledger.record_artifact("development_outcomes", outcome_store.content_checksum)
    ledger.record_artifact("response_space", inputs.response_space_checksum)
    ledger.record_artifact("factor_bank", inputs.factor_checksum)
    ledger.record_artifact("model", inputs.model_checksum)
    ledger.record_artifact("pair_manifest", inputs.manifest_checksum)
    ledger.record_artifact("environment", inputs.environment_checksum)
    ledger.record_artifact("method_lock", lock_checksum)
    ledger.record_artifact("frozen_prediction_bundle", bundle.bundle_checksum)

    # Step 9: confirm the sealed access count is ZERO (it never opened a seal).
    if futility.sealed_access_count != 0 or outcome_store.access_audit.sealed_access_count != 0:
        raise OutcomeLeakageError("invariant violated: Phase2a reported a non-zero sealed access")

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
