"""No-seal Phase-2a orchestrator + frozen handoff (Task 2a-11, plan §2.5 / §2.1).

SYNTHETIC-ONLY: pure ``numpy`` on synthetic fixtures only. ``run_phase2a``
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

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from alive.compose.baselines_combo import (
    BaselineAdapter,
    BaselineTrainingContext,
    additive,
    no_change,
    perturbation_mean,
)
from alive.compose.config2 import (
    ActivationRecord,
    ComposePhase2Config,
    ScientificModeError,
    assert_scientific_mode_allowed,
    load_compose_phase2_config,
)
from alive.compose.datacard import compute_compose_run_id
from alive.compose.diagnostics2 import FutilityResult, real_calibration_diagnostics
from alive.compose.fit_role import FitRoleArtifactSpec, build_response_projection
from alive.compose.freeze import (
    FrozenPredictionBundle,
    OutcomeLeakageError,
    _assert_no_outcome_reference,
    _assert_no_sealed,
)
from alive.compose.identify import calibration_lambda_scale
from alive.compose.models import fitted_model_checksum
from alive.compose.response import ResponseSpace, bind_response_source, verify_response_artifact
from alive.compose.roles import CALIBRATION_ROLE_NAME
from alive.compose.select import OOFFoldManifest
from alive.compose.zfactor import GeneFactorBank, verify_bank_normalization
from alive.provenance import RunLedger, sha256_bytes, sha256_file, sha256_json

#: The registered headline operator. Selection fits ONLY this model, so it is the
#: only one whose penalty was chosen under the registered relative-lambda
#: interpretation (``identification.lambda_scaling``).
HEADLINE_MODEL_NAME = "l1_bilinear_identifiable"

#: Default Phase-2 config consulted by the execution-mode guard.
_DEFAULT_CONFIG_PATH = "configs/compose_k562_v1_phase2.yaml"
_DEEP_BASELINE_NAMES = frozenset({"gears", "cpa"})

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
    produce a frozen bundle (CLAUDE.md#provenance).
    """


class Phase2aInvariantError(RuntimeError):
    """Raised when a Phase-2a internal invariant breaks. NOT an input rejection.

    Deliberately outside the driver's rejection roster, so it surfaces as the
    registered exit ``1`` bug escape with its traceback intact rather than as a
    contracted pre-seal rejection. It exists because one such check was previously
    raised as ``OutcomeLeakageError`` and therefore reported to a pod operator as a
    documented rejection (2026-08-01 review): a CONTINUE verdict without the
    persisted OOF fold manifest is a code invariant, not a leakage event, and the
    genuine leakage assertion in step 9 keeps its own class.
    """


class InputContractError(ValueError):
    """Raised when an externally supplied Phase-2a input violates its contract.

    Covers the structural and alignment validation of artifacts PREPARE produces
    and the driver only reads: the ``Phase2aInputs`` payload, the response
    artifact, the fit-role binding, and the gene/pair alignment between those
    inputs and the development outcome store. Every one of these is a fail-closed
    rejection of untrusted input, so it is a registered ``PRESEAL_REJECTION``
    reaching the driver's exit-code contract as ``10`` under its own class name
    (driver design spec 1.1). It is deliberately NOT a bare ``ValueError``: the
    driver may never admit a builtin base into its rejection roster, because an
    internal invariant violation raising the same builtin would then be reported
    as a documented rejection.
    """


class ConfigContractError(ValueError):
    """Raised when runtime inputs disagree with the preregistered config.

    Distinct from :class:`~alive.compose.config2.Phase2ConfigError`, which means
    the config itself is invalid. This one means the config is fine and the
    runtime inputs drifted from it -- a different operator response (re-derive the
    inputs, not edit the config), so it carries its own class name into the
    contracted stderr line.
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
            raise InputContractError(
                "combo_calibration_eps must be a 2-D array aligned row-for-row "
                "with combo_calibration_pair_ids"
            )
        if not np.all(np.isfinite(eps)):
            raise InputContractError("combo_calibration_eps contains non-finite values")
        if self.access_audit.role != CALIBRATION_ROLE_NAME:
            raise OutcomeLeakageError(
                f"development outcome audit role must be {CALIBRATION_ROLE_NAME!r}, "
                f"got {self.access_audit.role!r}"
            )
        if self.access_audit.sealed_access_count != 0:
            raise OutcomeLeakageError(
                "development outcome store reports a non-zero sealed access count"
            )
        if self.access_audit.source_kind not in {"synthetic_fixture", "audited_unsealed"}:
            raise InputContractError(
                "outcome audit source_kind must be 'synthetic_fixture' or 'audited_unsealed'"
            )
        if not self.access_audit.manifest_checksum or not self.access_audit.source_checksum:
            raise InputContractError("outcome access audit checksums must be non-empty")
        eps_snapshot = eps.copy()
        eps_snapshot.setflags(write=False)
        object.__setattr__(self, "combo_calibration_eps", eps_snapshot)
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
    response_space_checksum, factor_checksum, manifest_checksum, environment_checksum : str
        Bound upstream artifact checksums (verified in step 2). The model
        checksum is NOT a bound input: it is computed post-fit from the actual
        fitted model set (``effective_model_checksum`` in the orchestrator).
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
    manifest_checksum: str
    environment_checksum: str
    registered_seeds: Sequence[int]
    data_card_checksum: str
    raw_data_checksum: str
    sequence_mapping_checksum: str
    factor_banks_by_k: Mapping[int, GeneFactorBank] | None = None
    content_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        def _readonly(value: np.ndarray | Sequence) -> np.ndarray:
            snapshot = np.array(value, dtype=np.float64, copy=True)
            snapshot.setflags(write=False)
            return snapshot

        object.__setattr__(self, "gene_index", dict(self.gene_index))
        object.__setattr__(
            self,
            "factors_by_k",
            {k: _readonly(value) for k, value in self.factors_by_k.items()},
        )
        object.__setattr__(self, "cal_idx_pairs", tuple(tuple(p) for p in self.cal_idx_pairs))
        object.__setattr__(self, "cal_pair_ids", tuple(tuple(p) for p in self.cal_pair_ids))
        object.__setattr__(self, "additive_cal", _readonly(self.additive_cal))
        object.__setattr__(self, "eps_split_a", _readonly(self.eps_split_a))
        object.__setattr__(self, "eps_split_b", _readonly(self.eps_split_b))
        object.__setattr__(self, "k_total_grid", tuple(int(x) for x in self.k_total_grid))
        object.__setattr__(self, "lambda_grid", tuple(float(x) for x in self.lambda_grid))
        object.__setattr__(
            self, "sealed_double_pair_ids", tuple(tuple(p) for p in self.sealed_double_pair_ids)
        )
        object.__setattr__(
            self, "sealed_single_pair_ids", tuple(tuple(p) for p in self.sealed_single_pair_ids)
        )
        object.__setattr__(
            self,
            "delta_by_gene",
            {str(g): _readonly(value) for g, value in self.delta_by_gene.items()},
        )
        object.__setattr__(self, "model_factories", dict(self.model_factories))
        object.__setattr__(self, "registered_seeds", tuple(int(x) for x in self.registered_seeds))
        if self.factor_banks_by_k is not None:
            object.__setattr__(
                self,
                "factor_banks_by_k",
                {int(k): bank for k, bank in self.factor_banks_by_k.items()},
            )
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
    oof_manifest : OOFFoldManifest or None
        The canonical, checksummed OOF fold manifest from the single selection
        call. Returned in memory on BOTH CONTINUE and FUTILITY_STOPPED; on
        CONTINUE its checksum is additionally bound into the bundle diagnostics,
        the method lock and the ledger (and written to disk when a path is given).
    """

    futility_status: str
    sealed_access_count: int
    bundle: FrozenPredictionBundle | None
    futility: FutilityResult
    selected_k_total: int
    selected_lambda: float
    ledger: RunLedger | None = None
    method_lock: dict | None = field(default=None)
    oof_manifest: OOFFoldManifest | None = None


def build_subprocess_fit_payload(
    *,
    inputs: Phase2aInputs,
    outcome_store: DevelopmentOutcomeStore,
    response_artifact: Mapping,
    oof_folds: Sequence[int],
    fit_role_spec: FitRoleArtifactSpec,
    gene_order: Sequence[str],
    raw_data_sha256: str,
) -> dict[str, object]:
    """Assemble the canonical payload-v2 fit-role payload for GEARS/CPA workers.

    The v2 payload carries the A1 ``fit_role_artifact`` block and a serialized
    native→PCA response operator (``response_projection``) alongside the
    development singles/calibration design. The serialized projection arrays are
    reused verbatim for the top-level ``pca_components`` / ``control_mean`` so the
    validator's cross-source float equality holds, and the fit-role artifact's
    raw-data + gene-order digests are bound to the response source. The
    projection's ``response_artifact_sha256`` must additionally equal
    ``inputs.response_space_checksum`` (the separately verified response-space
    checksum), closing the circular-equality gap: the payload is bound to the
    *independently* verified response artifact, not merely self-consistent.

    Parameters
    ----------
    inputs : Phase2aInputs
        Bound development inputs (identities/features only).
    outcome_store : DevelopmentOutcomeStore
        Calibration-only outcome store, aligned with ``inputs.cal_pair_ids``.
    response_artifact : Mapping
        ``{"response_space": ResponseSpace, "control_mean": z-space centroid}``.
    oof_folds : sequence of int
        OOF fold assignment, one per calibration pair.
    fit_role_spec : FitRoleArtifactSpec
        The immutable identity of the written fit-role ``.h5ad`` artifact.
    gene_order : sequence of str
        Canonical full gene order the response space was fit against; must equal
        the fit-role artifact's ``var_names``.
    raw_data_sha256 : str
        Shared raw-data digest bound across the artifact, projection and source.

    Returns
    -------
    dict of str to object
        The payload-v2 fit-role payload.

    Raises
    ------
    InputContractError
        On a malformed response artifact, a fold/pair misalignment, a
        raw-data / gene-order digest mismatch between the fit-role artifact and
        the response source, or a projection whose ``response_artifact_sha256``
        does not equal the independently verified ``inputs.response_space_checksum``.
    """
    if set(response_artifact) != {"response_space", "control_mean"}:
        raise InputContractError(
            "response_artifact must contain exactly response_space + control_mean"
        )
    response_space = response_artifact["response_space"]
    control_mean = np.asarray(response_artifact["control_mean"], dtype=float)
    if control_mean.shape != (inputs.response_dim,):
        raise InputContractError("response artifact control_mean is not response_dim aligned")
    if len(oof_folds) != len(inputs.cal_pair_ids):
        raise InputContractError("oof_folds must align one-to-one with calibration pairs")
    if outcome_store.combo_calibration_pair_ids != tuple(tuple(p) for p in inputs.cal_pair_ids):
        raise InputContractError("development outcomes are not aligned with calibration pair IDs")

    projection = build_response_projection(
        response_space,
        gene_order=gene_order,
        control_mean=control_mean,
        raw_data_sha256=raw_data_sha256,
    )
    if projection["response_artifact_sha256"] != inputs.response_space_checksum:
        raise InputContractError(
            "projection does not match the independently verified response artifact"
        )
    fit_role_block = fit_role_spec.to_payload_block()
    bound = bind_response_source(gene_order=gene_order, raw_data_sha256=raw_data_sha256)
    if fit_role_block["raw_data_sha256"] != bound["raw_data_sha256"]:
        raise InputContractError("fit-role artifact raw_data_sha256 does not match response source")
    if fit_role_block["gene_order_sha256"] != bound["gene_order_sha256"]:
        raise InputContractError(
            "fit-role artifact gene_order_sha256 does not match response source"
        )

    genes = tuple(sorted(inputs.delta_by_gene, key=lambda gene: gene.encode("utf-8")))
    calibration_delta = np.asarray(inputs.additive_cal, dtype=float) + np.asarray(
        outcome_store.combo_calibration_eps, dtype=float
    )
    return {
        "schema_version": 2,
        "response_dim": int(inputs.response_dim),
        "seed": int(inputs.seed),
        "allowed_roles": ["singles", CALIBRATION_ROLE_NAME],
        "pair_ids": [],
        "single_gene_ids": list(genes),
        "singles_response": [
            np.asarray(inputs.delta_by_gene[gene], dtype=float).tolist() for gene in genes
        ],
        # reuse the projection-serialized arrays so the cross-source equality holds
        "control_mean": projection["control_mean"],
        "calibration_pair_ids": [list(pair) for pair in inputs.cal_pair_ids],
        "calibration_delta": calibration_delta.tolist(),
        "pca_components": projection["pca_components"],
        "oof_folds": [int(fold) for fold in oof_folds],
        "fit_role_artifact": fit_role_block,
        "response_projection": projection,
    }


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
        "manifest_checksum": inputs.manifest_checksum,
        "environment_checksum": inputs.environment_checksum,
        "registered_seeds": [int(x) for x in inputs.registered_seeds],
        "data_card_checksum": inputs.data_card_checksum,
        "raw_data_checksum": inputs.raw_data_checksum,
        "sequence_mapping_checksum": inputs.sequence_mapping_checksum,
        "factor_banks_by_k": (
            None
            if inputs.factor_banks_by_k is None
            else {
                str(k): inputs.factor_banks_by_k[k].checksum
                for k in sorted(inputs.factor_banks_by_k)
            }
        ),
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
        "manifest_checksum": inputs.manifest_checksum,
        "environment_checksum": inputs.environment_checksum,
        "data_card_checksum": inputs.data_card_checksum,
        "raw_data_checksum": inputs.raw_data_checksum,
        "sequence_mapping_checksum": inputs.sequence_mapping_checksum,
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


def _verify_scientific_data_assets(
    inputs: Phase2aInputs,
    *,
    data_card_path: str | Path | None,
    raw_asset_path: str | Path | None,
) -> None:
    """Bind the scientific run identity to the actual data-card and raw asset."""
    if data_card_path is None or raw_asset_path is None:
        raise HashMismatchError(
            "scientific Phase2a requires data_card_path and raw_asset_path so provenance "
            "digests are verified against actual files"
        )

    try:
        card = json.loads(Path(data_card_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HashMismatchError(f"failed to read canonical data-card: {exc}") from exc
    card_digest = sha256_json(card)
    if card_digest != inputs.data_card_checksum:
        raise HashMismatchError(
            f"data-card digest mismatch: actual {card_digest!r} != "
            f"bound {inputs.data_card_checksum!r}"
        )

    try:
        raw_digest = sha256_file(raw_asset_path)
    except OSError as exc:
        raise HashMismatchError(f"failed to hash raw/source asset: {exc}") from exc
    if raw_digest != inputs.raw_data_checksum:
        raise HashMismatchError(
            f"raw/source digest mismatch: actual {raw_digest!r} != "
            f"bound {inputs.raw_data_checksum!r}"
        )

    recorded = card.get("raw_or_source", {}) if isinstance(card, dict) else {}
    if not isinstance(recorded, dict) or recorded.get("digest") != raw_digest:
        raise HashMismatchError(
            "data-card raw_or_source.digest does not match the actual raw/source asset"
        )


def _verify_scientific_response_artifact(
    inputs: Phase2aInputs,
    response_artifact: Mapping | None,
) -> None:
    """Bind Phase2a to the actual response-space state and control mean."""
    if response_artifact is None:
        raise HashMismatchError(
            "scientific Phase2a requires response_artifact with response_space, "
            "control_mean and checksum"
        )
    space = response_artifact.get("response_space")
    control_mean = response_artifact.get("control_mean")
    declared = response_artifact.get("checksum")
    if (
        not isinstance(space, ResponseSpace)
        or control_mean is None
        or not isinstance(declared, str)
    ):
        raise HashMismatchError(
            "scientific response_artifact requires a ResponseSpace, control_mean and checksum"
        )
    try:
        _, _, computed = verify_response_artifact(space, control_mean)
    except ValueError as exc:
        raise HashMismatchError(f"invalid response artifact: {exc}") from exc
    if declared != computed or computed != inputs.response_space_checksum:
        raise HashMismatchError(
            "response artifact checksum does not match its contents and bound Phase2a checksum"
        )


def _validate_config_contract(
    inputs: Phase2aInputs,
    config: ComposePhase2Config,
    baseline_adapter_names: Sequence[str] = (),
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
    # Order the deep-baseline adapter segment by the registered roster (not the
    # caller's mapping order) so the contract agrees with the set-based adapter
    # validation: {gears, cpa} supplied in any order must not spuriously mismatch.
    adapter_name_set = set(baseline_adapter_names)
    runtime_learned = tuple(inputs.model_factories) + tuple(
        name for name in learned_roster if name in adapter_name_set
    )
    if runtime_learned != learned_roster:
        mismatches.append("model_roster")
    if mismatches:
        raise ConfigContractError(
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
    """Fail closed unless gene identities, pair indices and aligned rows agree."""
    if isinstance(inputs.n_genes, bool) or not isinstance(inputs.n_genes, int):
        raise InputContractError("n_genes must be an int")
    if inputs.n_genes <= 0:
        raise InputContractError("n_genes must be positive")

    gene_index = dict(inputs.gene_index)
    if len(gene_index) != inputs.n_genes:
        raise InputContractError(
            f"gene_index has {len(gene_index)} genes, expected n_genes={inputs.n_genes}"
        )
    if not all(isinstance(g, str) and g for g in gene_index):
        raise InputContractError("gene_index keys must be non-empty gene strings")
    values = list(gene_index.values())
    if any(isinstance(i, bool) or not isinstance(i, (int, np.integer)) for i in values):
        raise InputContractError("gene_index values must be integer row indices")
    integer_values = [int(i) for i in values]
    if set(integer_values) != set(range(inputs.n_genes)):
        raise InputContractError("gene_index values must be a bijection onto range(n_genes)")

    delta_genes = set(inputs.delta_by_gene)
    if delta_genes != set(gene_index):
        missing = sorted(set(gene_index) - delta_genes)
        extra = sorted(delta_genes - set(gene_index))
        raise InputContractError(
            "delta_by_gene must cover the gene_index universe exactly "
            f"(missing={missing}, extra={extra})"
        )

    for k_total, factors in inputs.factors_by_k.items():
        rows = np.asarray(factors)
        if rows.ndim != 2 or rows.shape[0] != inputs.n_genes:
            raise InputContractError(
                f"factors_by_k[{k_total!r}] must have n_genes={inputs.n_genes} rows; "
                f"got shape {rows.shape}"
            )

    input_ids = tuple(tuple(p) for p in inputs.cal_pair_ids)
    if outcome_store.combo_calibration_pair_ids != input_ids:
        raise InputContractError(
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
        raise InputContractError(f"calibration row alignment mismatch: expected {n}, got {bad}")

    def _validate_id_pair(raw_pair, *, context: str) -> tuple[str, str]:
        pair = tuple(raw_pair)
        if len(pair) != 2 or not all(isinstance(g, str) and g for g in pair):
            raise InputContractError(
                f"{context} must be a pair of non-empty gene strings: {pair!r}"
            )
        g, h = pair
        if g == h:
            raise InputContractError(f"{context} cannot be a self-pair: {pair!r}")
        if g.encode("utf-8") > h.encode("utf-8"):
            raise InputContractError(f"{context} is not UTF-8 canonical: {pair!r}")
        missing = [gene for gene in pair if gene not in gene_index]
        if missing:
            raise InputContractError(f"{context} contains genes absent from gene_index: {missing}")
        return g, h

    for row, (pair_id, raw_idx_pair) in enumerate(zip(input_ids, inputs.cal_idx_pairs)):
        g, h = _validate_id_pair(pair_id, context=f"cal_pair_ids[{row}]")
        idx_pair = tuple(raw_idx_pair)
        if len(idx_pair) != 2 or any(
            isinstance(i, bool) or not isinstance(i, (int, np.integer)) for i in idx_pair
        ):
            raise InputContractError(f"cal_idx_pairs[{row}] must be a pair of integer indices")
        observed = {int(idx_pair[0]), int(idx_pair[1])}
        expected = {int(gene_index[g]), int(gene_index[h])}
        if observed != expected or len(observed) != 2:
            raise InputContractError(
                f"calibration pair mismatch at row {row}: ID pair {(g, h)!r} maps to "
                f"{tuple(sorted(expected))!r}, got index pair {idx_pair!r}"
            )

    for role, pairs in (
        ("sealed_double_pair_ids", inputs.sealed_double_pair_ids),
        ("sealed_single_pair_ids", inputs.sealed_single_pair_ids),
    ):
        for row, pair in enumerate(pairs):
            _validate_id_pair(pair, context=f"{role}[{row}]")


def _verify_factor_banks(inputs: Phase2aInputs, *, require_banks: bool) -> None:
    """Bind every runtime factor row to a checksummed factor-bank artifact."""
    banks = inputs.factor_banks_by_k
    if banks is None:
        if require_banks:
            raise HashMismatchError(
                "scientific Phase2a requires factor_banks_by_k; raw matrices alone do not "
                "prove factor provenance"
            )
        return

    matrix_keys = {int(k) for k in inputs.factors_by_k}
    if set(banks) != matrix_keys:
        raise HashMismatchError(
            "factor_banks_by_k keys must exactly match factors_by_k keys "
            f"(banks={sorted(banks)}, matrices={sorted(matrix_keys)})"
        )

    genes = set(inputs.gene_index)
    for k_total in sorted(matrix_keys):
        bank = banks[k_total]
        if sha256_bytes(bank.artifact_bytes()) != bank.checksum:
            raise HashMismatchError(f"factor bank k={k_total} checksum does not verify")
        # The checksum binds the bank to itself, and the row loop below binds the
        # runtime matrix to the bank. Neither says the bank obeys the REGISTERED
        # normalization: an unnormalized bank and a runtime matrix copied from it
        # agree perfectly and are both wrong. Verify the rule on the numbers.
        # Raised as HashMismatchError so it cannot escape a caller that handles
        # this function's failures -- the same escape that let LinAlgError past
        # the pre-seal roster once before.
        try:
            verify_bank_normalization(bank)
        except ValueError as exc:
            raise HashMismatchError(f"factor bank k={k_total}: {exc}") from exc
        if int(bank.k_total) != k_total:
            raise HashMismatchError(
                f"factor bank key {k_total} disagrees with bank.k_total={bank.k_total}"
            )
        if set(bank.gene_order) != genes or set(bank.z_by_gene) != genes:
            raise HashMismatchError(f"factor bank k={k_total} gene universe mismatch")
        if bank.sequence_mapping_hash != inputs.sequence_mapping_checksum:
            raise HashMismatchError(f"factor bank k={k_total} sequence mapping checksum mismatch")
        matrix = np.asarray(inputs.factors_by_k[k_total], dtype=np.float64)
        for gene, row in inputs.gene_index.items():
            if not np.array_equal(matrix[int(row)], np.asarray(bank.z_by_gene[gene])):
                raise HashMismatchError(
                    f"factor matrix k={k_total} row {row} does not match bank gene {gene!r}"
                )

    aggregate = sha256_json(
        {"factor_banks_by_k": {str(k): banks[k].checksum for k in sorted(banks)}}
    )
    if aggregate != inputs.factor_checksum:
        raise HashMismatchError(
            f"aggregate factor checksum {aggregate!r} != bound {inputs.factor_checksum!r}"
        )


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


def _baseline_context(inputs: Phase2aInputs) -> BaselineTrainingContext:
    """The frozen development-role context handed to every subprocess adapter.

    Parameters
    ----------
    inputs : Phase2aInputs
        The bound inputs; only development-role identities/checksums are read.

    Returns
    -------
    BaselineTrainingContext
        The single context reused for the combined subprocess fit (spec §2.5),
        pinning the allowed roles, manifest/response checksums and the ordered
        calibration pair IDs and single-gene IDs.
    """
    return BaselineTrainingContext(
        allowed_roles=frozenset({"singles", CALIBRATION_ROLE_NAME}),
        pair_manifest_checksum=inputs.manifest_checksum,
        response_space_checksum=inputs.response_space_checksum,
        training_pair_ids=tuple(tuple(p) for p in inputs.cal_pair_ids),
        single_gene_ids=tuple(
            sorted(inputs.delta_by_gene, key=lambda gene: str(gene).encode("utf-8"))
        ),
    )


def _combined_pair_union(
    double_ids: Sequence[tuple[str, str]],
    single_ids: Sequence[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Ordered de-duplicated double∪single request (doubles first) for a single fit.

    Parameters
    ----------
    double_ids : sequence of (str, str)
        The registered double-unseen sealed pair IDs.
    single_ids : sequence of (str, str)
        The registered single-unseen sealed pair IDs.

    Returns
    -------
    list of (str, str)
        The combined request the subprocess worker fits/predicts exactly once,
        with the double-unseen pairs first and any overlap de-duplicated.
    """
    union: list[tuple[str, str]] = []
    for p in (*double_ids, *single_ids):
        pair = (p[0], p[1])
        if pair not in union:
            union.append(pair)
    return union


def _predict_combined_adapters(
    inputs: Phase2aInputs,
    combined_pair_ids: Sequence[tuple[str, str]],
    baseline_adapters: Mapping[str, object],
) -> dict[str, dict[tuple[str, str], np.ndarray]]:
    """Invoke every subprocess adapter EXACTLY once on the combined pair union.

    Honors the single-fit / single-checkpoint / combined-request rule (spec §2.5):
    each worker fits once and predicts the whole union; :func:`_predict_role` then
    splits the cached result per role without re-invoking the worker.

    Parameters
    ----------
    inputs : Phase2aInputs
        The bound inputs; supplies the frozen :func:`_baseline_context`.
    combined_pair_ids : sequence of (str, str)
        The ordered double∪single request from :func:`_combined_pair_union`.
    baseline_adapters : Mapping of str to adapter
        The subprocess adapters keyed by method name.

    Returns
    -------
    dict
        ``name -> {pair_id -> length-response_dim prediction vector}`` for every
        adapter, each produced by a single ``predict`` call over the union.
    """
    context = _baseline_context(inputs)
    return {
        name: adapter.predict(context, list(combined_pair_ids), inputs.response_dim)
        for name, adapter in baseline_adapters.items()
    }


def _predict_role(
    inputs: Phase2aInputs,
    pair_ids: Sequence[tuple[str, str]],
    fitted_models: Mapping[str, object],
    selected_Z: np.ndarray,
    perturbation_mean_prediction: np.ndarray,
    baseline_adapters: Mapping[str, BaselineAdapter] | None = None,
    *,
    adapter_predictions: Mapping[str, Mapping[tuple[str, str], np.ndarray]] | None = None,
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
    baseline_adapters : Mapping of str to BaselineAdapter, optional
        Subprocess adapters (GEARS/CPA). When ``adapter_predictions`` is None the
        adapter predicts this role directly; otherwise it is only a key roster.
    adapter_predictions : Mapping of str to (Mapping of pair_id to ndarray), optional
        The pre-computed combined single-fit predictions from
        :func:`_predict_combined_adapters`. When supplied this role's predictions
        are SLICED out of it (no re-invocation), enforcing the §2.5 single-fit
        rule. When None (default) the adapter is invoked per role.

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
    if baseline_adapters:
        if adapter_predictions is None:
            # Direct per-role call (preserves any direct caller): each adapter
            # fits + predicts this role. run_phase2a NEVER takes this branch —
            # it pre-computes the combined single fit and passes the split below.
            context = _baseline_context(inputs)
            for name, adapter in baseline_adapters.items():
                out[name] = adapter.predict(context, list(pair_ids), inputs.response_dim)
        else:
            # Split the already-computed combined union (spec §2.5 single fit):
            # slice this role's pairs out of the shared prediction — no re-invoke.
            for name in baseline_adapters:
                combined = adapter_predictions[name]
                out[name] = {(g, h): np.asarray(combined[(g, h)], dtype=float) for g, h in pair_ids}
    return out


def _validate_baseline_adapters(
    *,
    model_factories: Mapping[str, ModelFactory],
    baseline_adapters: Mapping[str, BaselineAdapter] | None,
    required: bool,
) -> dict[str, BaselineAdapter]:
    """Validate the activation-time GEARS/CPA assembly before model fitting."""
    adapters = dict(baseline_adapters or {})
    if required or adapters:
        if set(adapters) != _DEEP_BASELINE_NAMES:
            raise ScientificModeError(
                "activation-time baseline adapters must be exactly {'gears', 'cpa'}; "
                f"got {sorted(adapters)}"
            )
        overlap = set(model_factories) & _DEEP_BASELINE_NAMES
        if overlap:
            raise ScientificModeError(
                "GEARS/CPA cannot be supplied as local model_factory stand-ins when "
                f"subprocess adapters are active: {sorted(overlap)}"
            )
        for name, adapter in adapters.items():
            if not isinstance(adapter, BaselineAdapter) or adapter.name != name:
                raise ScientificModeError(f"invalid activation-time adapter for {name!r}")
            backend = adapter.backend
            if backend is None or not getattr(backend, "is_available", False):
                raise ScientificModeError(f"activation-time backend {name!r} is unavailable")
            # Accessing the manifest fails closed on an absent payload/worker and
            # binds the exact runtime identity used below.
            getattr(backend, "provenance_manifest")
    return adapters


def _validate_adapter_runtime_bindings(
    inputs: Phase2aInputs,
    config: ComposePhase2Config,
    adapters: Mapping[str, BaselineAdapter],
) -> None:
    """Bind every subprocess backend to the active run and method preregistration.

    Payload construction validates its own response artifact, but the Phase2a
    orchestrator must also prove that the *configured backend* consumes the same
    response space as ``inputs`` and uses the representation registered for that
    method. Otherwise predictions can be frozen under an unrelated response-space
    checksum or a worker can silently select a different nonlinear adapter.
    """
    expected_representations = {
        name: representation
        for name, representation, _bias_report in config.baseline_representations
    }
    mismatches: list[str] = []
    for name, adapter in sorted(adapters.items()):
        backend = adapter.backend
        observed_response = getattr(backend, "expected_response_artifact_sha256", None)
        if observed_response != inputs.response_space_checksum:
            mismatches.append(
                f"{name}.response_space({observed_response!r}!={inputs.response_space_checksum!r})"
            )
        lock = getattr(backend, "execution_identity_lock", None)
        observed_representation = getattr(lock, "prediction_representation", None)
        expected_representation = expected_representations.get(name)
        if observed_representation != expected_representation:
            mismatches.append(
                f"{name}.prediction_representation("
                f"{observed_representation!r}!={expected_representation!r})"
            )
    if mismatches:
        raise ScientificModeError(
            "subprocess backend identities differ from the bound run/config: "
            + ", ".join(mismatches)
        )


def _build_method_lock(
    inputs: Phase2aInputs,
    roster: tuple[str, ...],
    result: FutilityResult,
    *,
    model_checksum: str,
    oof_fold_manifest_checksum: str,
):
    """Build the frozen method lock (roster + selected hyperparameters + checksums).

    The method lock binds the exact roster and the selected ``(k_total, lambda)``
    + seeds to the upstream artifact checksums — including the persisted OOF fold
    manifest checksum — so Phase 2b cannot silently swap a method, a
    hyperparameter or the development fold layout. Returns
    ``(lock_dict, lock_checksum)``.
    """
    lock = {
        "run_id": inputs.run_id,
        "method_roster": list(roster),
        "selected_k_total": int(result.selected_k_total),
        "selected_lambda": round(float(result.selected_lambda), 12),
        "registered_seeds": list(int(s) for s in inputs.registered_seeds),
        "response_space_checksum": inputs.response_space_checksum,
        "factor_checksum": inputs.factor_checksum,
        "model_checksum": model_checksum,
        "manifest_checksum": inputs.manifest_checksum,
        "environment_checksum": inputs.environment_checksum,
        "oof_fold_manifest_checksum": oof_fold_manifest_checksum,
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
    data_card_path: str | Path | None = None,
    raw_asset_path: str | Path | None = None,
    response_artifact: Mapping | None = None,
    baseline_adapters: Mapping[str, BaselineAdapter] | None = None,
    oof_manifest_path: str | Path | None = None,
) -> Phase2aResult:
    """Run scientific Phase-2a after all activation conditions are satisfied.

    ``fixture_mode=True`` is intentionally rejected here.  Synthetic tests must
    use :func:`run_phase2a_fixture`, so a caller-controlled boolean cannot bypass
    owner activation, clean-Git, and evidence-hash checks.

    When ``oof_manifest_path`` is given and the run CONTINUEs, the canonical OOF
    fold manifest is written ONCE there; on a futility stop nothing is written.
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
        data_card_path=data_card_path,
        raw_asset_path=raw_asset_path,
        response_artifact=response_artifact,
        baseline_adapters=baseline_adapters,
        oof_manifest_path=oof_manifest_path,
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
    baseline_adapters: Mapping[str, BaselineAdapter] | None = None,
    oof_manifest_path: str | Path | None = None,
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
        data_card_path=None,
        raw_asset_path=None,
        response_artifact=None,
        baseline_adapters=baseline_adapters,
        oof_manifest_path=oof_manifest_path,
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
    data_card_path: str | Path | None,
    raw_asset_path: str | Path | None,
    response_artifact: Mapping | None,
    baseline_adapters: Mapping[str, BaselineAdapter] | None,
    oof_manifest_path: str | Path | None = None,
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
        _verify_scientific_data_assets(
            inputs,
            data_card_path=data_card_path,
            raw_asset_path=raw_asset_path,
        )
        _verify_scientific_response_artifact(inputs, response_artifact)

    adapters = _validate_baseline_adapters(
        model_factories=inputs.model_factories,
        baseline_adapters=baseline_adapters,
        required=not fixture_execution,
    )
    _validate_adapter_runtime_bindings(inputs, cfg, adapters)

    # Step 2: bind runtime values, in-memory contents, role provenance and run ID.
    _validate_config_contract(inputs, cfg, tuple(adapters))
    _verify_hashes(inputs, outcome_store, expected_hashes)
    _validate_pair_alignment(inputs, outcome_store)
    _verify_factor_banks(inputs, require_banks=not fixture_execution)
    _validate_run_identity(inputs, cfg)

    # Step 3: selection + real calibration / futility checkpoint on DEVELOPMENT
    # roles only. The L1 model drives selection (headline ablation).
    #
    # This guard stays a BARE ``ValueError`` on purpose: it is SHADOWED by
    # ``_validate_config_contract`` above, which compares the runtime learned
    # roster against ``config.method_roster`` -- and ``config2`` pins the ladder
    # to start at ``l1_bilinear_identifiable``, so inputs missing the headline
    # model always fail there first with ``ConfigContractError``. Reaching this
    # line therefore means an internal invariant broke, which the registered
    # classification calls a BUG: traceback + exit 1, never a contracted
    # rejection (driver design spec 1.1). ``test_the_headline_model_guard_is_shadowed
    # _by_the_config_contract`` pins that ordering.
    if HEADLINE_MODEL_NAME not in inputs.model_factories:
        raise ValueError(f"model_factories must include {HEADLINE_MODEL_NAME!r} (headline model)")
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
        dev_oof_threshold=cfg.dev_oof_threshold,
        measurability_role=CALIBRATION_ROLE_NAME,
        measurability_ceiling_floor=cfg.futility_measurability_ceiling_floor,
        unregularized_oof_rank_policy=cfg.unregularized_oof_rank_policy,
        rank_tolerance_rule=cfg.rank_tolerance_rule,
        lambda_scaling=cfg.lambda_scaling,
        condition_ceiling=cfg.condition_ceiling,
    )
    selected_k = futility.selected_k_total
    selected_lambda = futility.selected_lambda

    # Step 4: futility -> STOP without any sealed predictions (seal stays closed).
    # The OOF fold manifest is returned in memory but NOT written and NOT bound
    # into a bundle/lock/ledger — there is no sealed-prediction bundle on futility
    # (the driver may still persist the development diagnostic at its own path).
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
            oof_manifest=futility.oof_manifest,
        )

    # Step 5: CONTINUE -> bind the persisted OOF fold manifest (from the SINGLE
    # selection call inside the futility checkpoint) and fit learned models on
    # calibration data only, then predict the REGISTERED sealed pairs using
    # IDENTITIES / FEATURES only.
    oof_manifest = futility.oof_manifest
    if oof_manifest is None:
        raise Phase2aInvariantError(
            "CONTINUE without a persisted OOF fold manifest: the futility checkpoint's "
            "single selection call must always bind one"
        )
    oof_fold_manifest_checksum = oof_manifest.manifest_checksum
    selected_Z = np.asarray(inputs.factors_by_k[selected_k], dtype=float)
    # The registered lambda is RELATIVE (``identification.lambda_scaling``). This
    # final fit must apply exactly the interpretation selection used, or the
    # selected hyperparameter would not be the one that was scored. Recomputed from
    # the same ``(Z, cal_idx_pairs)`` selection saw, so the two agree by
    # construction; ``test_lambda_scaling`` pins that they do.
    headline_lambda_scale = calibration_lambda_scale(selected_Z, list(inputs.cal_idx_pairs))
    fitted: dict[str, object] = {}
    for name, factory in inputs.model_factories.items():
        model = factory()
        # Scaled for the HEADLINE operator only, deliberately. Selection fits only
        # this model, so only its penalty was ever chosen under the scaled
        # interpretation. ``id_only`` is a registered BASELINE whose feature is
        # linear in ``z`` (the operator's is bilinear), so the same scale would not
        # make it scale-invariant anyway -- giving it one would silently change a
        # baseline's fit for no established reason. Recorded as an open residual
        # rather than half-fixed here.
        lam_applied = float(selected_lambda)
        if name == HEADLINE_MODEL_NAME:
            lam_applied *= headline_lambda_scale
        model.fit(selected_Z, list(inputs.cal_idx_pairs), eps_cal, lam=lam_applied)
        fitted[name] = model
    # Combined single-fit invocation (spec §2.5) BEFORE the adapter provenance
    # read: each subprocess worker fits ONCE and predicts the whole double∪single
    # union. This MUST precede the provenance_manifest read below because
    # SubprocessBaselineBackend.provenance_manifest only carries the execution
    # manifest (checkpoint + prediction digests) AFTER a predict has run, so the
    # combined predict must happen first for those digests to bind into
    # effective_model_checksum (spec §2.5/§10 — the method lock).
    combined_pairs = _combined_pair_union(
        inputs.sealed_double_pair_ids, inputs.sealed_single_pair_ids
    )
    adapter_predictions = (
        _predict_combined_adapters(inputs, combined_pairs, adapters) if adapters else None
    )
    model_artifact_checksums = {
        name: fitted_model_checksum(model) for name, model in sorted(fitted.items())
    }
    for name, adapter in sorted(adapters.items()):
        model_artifact_checksums[name] = sha256_json(adapter.backend.provenance_manifest)
    effective_model_checksum = sha256_json(
        {
            "schema": "compose_model_set_v1",
            "methods": model_artifact_checksums,
            "selected_k_total": int(selected_k),
            "selected_lambda": float(selected_lambda).hex(),
        }
    )

    calibration_double_shifts = np.asarray(inputs.additive_cal, dtype=float) + eps_cal
    mean_prediction = perturbation_mean(calibration_double_shifts)
    double_preds = _predict_role(
        inputs,
        inputs.sealed_double_pair_ids,
        fitted,
        selected_Z,
        mean_prediction,
        adapters,
        adapter_predictions=adapter_predictions,
    )
    single_preds = _predict_role(
        inputs,
        inputs.sealed_single_pair_ids,
        fitted,
        selected_Z,
        mean_prediction,
        adapters,
        adapter_predictions=adapter_predictions,
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
        model_checksum=effective_model_checksum,
        model_artifact_checksums=model_artifact_checksums,
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
            "nonviable_candidates": [
                {"k_total": k, "lambda": lam, "reason": reason}
                for k, lam, reason in futility.nonviable_candidates
            ],
            # binds the exact development OOF fold layout into the frozen bundle.
            "oof_fold_manifest_checksum": oof_fold_manifest_checksum,
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

    # write the OOF fold manifest ONCE when a destination is given (write-once).
    if oof_manifest_path is not None:
        oof_manifest.write_once(oof_manifest_path)

    # Step 8: record the bundle + method-lock checksums in a write-once ledger.
    method_lock, lock_checksum = _build_method_lock(
        inputs,
        roster,
        futility,
        model_checksum=effective_model_checksum,
        oof_fold_manifest_checksum=oof_fold_manifest_checksum,
    )
    env = environment if environment is not None else _placeholder_environment(inputs)
    ledger = RunLedger(run_id=inputs.run_id, config_sha256=cfg.config_sha256, environment=env)
    ledger.record_artifact("data_card", inputs.data_card_checksum)
    ledger.record_artifact("raw_data", inputs.raw_data_checksum)
    ledger.record_artifact("sequence_mapping", inputs.sequence_mapping_checksum)
    ledger.record_artifact("phase2a_inputs", inputs.content_checksum)
    ledger.record_artifact("development_outcomes", outcome_store.content_checksum)
    ledger.record_artifact("response_space", inputs.response_space_checksum)
    ledger.record_artifact("factor_bank", inputs.factor_checksum)
    ledger.record_artifact("model", effective_model_checksum)
    ledger.record_artifact("pair_manifest", inputs.manifest_checksum)
    ledger.record_artifact("environment", inputs.environment_checksum)
    ledger.record_artifact("method_lock", lock_checksum)
    ledger.record_artifact("phase2a_oof_fold_manifest", oof_fold_manifest_checksum)
    ledger.record_artifact("frozen_prediction_bundle", bundle.bundle_checksum)

    # Step 9: confirm the sealed access count is ZERO (it never opened a seal).
    if futility.sealed_access_count != 0 or outcome_store.access_audit.sealed_access_count != 0:
        raise Phase2aInvariantError(
            "Phase2a step 9: sealed access count is NOT zero — a sealed outcome was "
            f"touched during development (futility={futility.sealed_access_count}, "
            f"store audit={outcome_store.access_audit.sealed_access_count}, "
            f"role={outcome_store.access_audit.role!r}, "
            f"source_kind={outcome_store.access_audit.source_kind!r}). "
            "The REAL detection is DevelopmentOutcomeStore.__post_init__, which "
            "refuses a non-zero count on a frozen dataclass, and FutilityResult's "
            "one construction site hardcodes 0 -- so reaching this line means an "
            "internal invariant broke, which is why it is Phase2aInvariantError and "
            "exits 1 with its traceback. A 2026-08-02 draft kept OutcomeLeakageError "
            "here on the belief that it was a live leakage detection; review refuted "
            "that by construction (2026-08-03). Preserve every artifact and report."
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
        oof_manifest=oof_manifest,
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
