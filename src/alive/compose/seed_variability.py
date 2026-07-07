"""COMPOSE development seed-variability: fold jobs + top-level entry (D2 Tasks 3-5).

SYNTHETIC-SAFE: pure ``numpy`` + a re-derived fit-role artifact. This module builds,
for ONE gene-disjoint OOF calibration fold, a fold-scoped fit job whose worker payload
trains ONLY on that fold's TRAIN combo pairs. The fold's held-out TEST pairs and its
cross-group EXCLUDED pairs are fully absent from both the fold-scoped fit-role artifact
and the payload — this is the leakage-critical heart of D2's per-seed OOF error
measurement.

Task 5 adds the strict report containers (:class:`SeedVariabilityStatus`,
:class:`CoverageReport`, :class:`FoldExecutionRecord`, :class:`SeedComparatorSummary`,
:class:`SeedVariabilityReport`) and the production entry
:func:`development_seed_variability`, which ties Tasks 1-4 together into one
self-checksummed report over the two refittable comparators ({gears, cpa}).

It opens NO seal, reads NO sealed outcome, and imports NO ``gears`` / ``cpa`` (the
subprocess seam runs the real workers pod-only). Development calibration outcomes only.

Fold-scoping mechanism (spec §4, plan Task 3).  A fold's held-out/cross-group combos
are made absent by re-deriving a :class:`~alive.compose.fit_role.ComposeFitRoleExtractor`
over the ALREADY-validated base fit-role artifact with

* ``calibration_pair_ids`` = this fold's TRAIN pairs, and
* ``sealed_pair_ids``      = this fold's TEST pairs ∪ its cross-group EXCLUDED pairs.

Every base calibration combo (which the manifest guarantees is train ∪ test ∪ excluded)
then classifies as ``combo_calibration`` (train, retained) or sealed (test/excluded →
``None`` → excluded, never read). No combo outside train ∪ test ∪ excluded remains to
raise. The generated fold artifact is validated and independently proven to carry no
held-out/excluded combo token before it is bound into the job.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import numpy as np

from alive.compose.baseline_subprocess import _REQUIRED_KEYS
from alive.compose.baselines_combo import BaselineAdapter, BaselineTrainingContext
from alive.compose.config2 import ComposePhase2Config
from alive.compose.fit_role import (
    ComposeFitRoleExtractor,
    FitRoleArtifactSpec,
    _file_sha256,
    extract_fit_roles,
    generate_fit_role_artifact,
    validate_fit_role_artifact,
)
from alive.compose.phase2a import (
    DevelopmentOutcomeStore,
    Phase2aInputs,
    _outcome_store_checksum,
    build_subprocess_fit_payload,
)
from alive.compose.provenance2 import PROTOCOL
from alive.compose.select import OOFFoldManifest
from alive.io import atomic_write_once
from alive.provenance import sha256_json

_CONTROL_TOKEN = "control"
_COMBO_SEP = "_"


class FoldJobError(ValueError):
    """Raised on any fold-job alignment, artifact or leakage-proof violation.

    Covers a manifest/input/store misalignment, an out-of-range fold, a base
    fit-role artifact whose bytes no longer match its spec, a train/position↔ID
    disagreement, an ``oof_folds`` label that disagrees with the verified manifest,
    and — the load-bearing guard — any held-out or cross-group combo token surviving
    into the fold-scoped fit-role artifact. Every path fails closed.
    """


class FoldExecutionError(ValueError):
    """Raised when a single fold job cannot be executed to a verified result.

    Covers a backend whose ``provenance_manifest`` never reaches its post-predict
    form (no verified ``execution_manifest``), so no real worker/checkpoint/request
    digest can be captured. Fails closed rather than synthesizing a checksum.
    """


class SeedAssemblyError(ValueError):
    """Raised when a seed's covered-order OOF reassembly is not exactly-once.

    A missing, duplicate, extra, non-finite or dimension-mismatched covered-pair
    prediction — or a covered pair with no development delta truth — makes the
    whole seed fail rather than yielding a partial or silently-imputed scalar.
    """


@dataclass(frozen=True)
class FoldJob:
    """A controller-side, fold-scoped fit job for one ``(method, seed, fold)``.

    All fold metadata lives HERE, never inside :attr:`payload`, so the worker payload
    keeps exactly :data:`alive.compose.baseline_subprocess._REQUIRED_KEYS`.

    Attributes
    ----------
    method : str
        The seed-refittable comparator name (``"gears"`` / ``"cpa"``).
    seed : int
        The registered random seed this job is bound to.
    fold_index : int
        Zero-based index of the OOF fold in the manifest.
    payload : Mapping of str to object
        The payload-v2 fit-role payload restricted to this fold's TRAIN pairs. Its
        key set equals :data:`_REQUIRED_KEYS` exactly.
    test_pair_ids : tuple of tuple of str
        The fold's held-out TEST pair IDs (the OOF measurement targets, predicted by
        the worker but absent from the fit set).
    excluded_pair_ids : tuple of tuple of str
        The fold's cross-group EXCLUDED pair IDs (absent from the fit set).
    fit_role_artifact_path : str
        Filesystem path of the write-once fold-scoped fit-role ``.h5ad``.
    fit_role_artifact_sha256 : str
        ``"sha256:"``-prefixed digest of the fold-scoped artifact's bytes.
    train_source_checksum : str
        Content checksum of the train-only :class:`DevelopmentOutcomeStore` (the
        development delta source restricted to this fold's train pairs).
    fold_manifest_checksum : str
        The verified OOF fold manifest's self-excluding checksum.
    """

    method: str
    seed: int
    fold_index: int
    payload: Mapping[str, object]
    test_pair_ids: tuple[tuple[str, str], ...]
    excluded_pair_ids: tuple[tuple[str, str], ...]
    fit_role_artifact_path: str
    fit_role_artifact_sha256: str
    train_source_checksum: str
    fold_manifest_checksum: str


@dataclass(frozen=True)
class FoldExecutionResult:
    """The verified outcome of executing ONE ``(method, seed, fold)`` job.

    Holds the fold's held-out TEST-pair predictions together with the *real*
    provenance digests captured from the backend's post-predict
    ``provenance_manifest`` — never a value synthesized from ``{method, seed}``.
    These digests bind the executed worker, its configured payload, its verified
    checkpoint and the exact ordered request into the per-seed OOF measurement.

    Attributes
    ----------
    method : str
        The seed-refittable comparator name this job ran (``"gears"`` / ``"cpa"``).
    seed : int
        The registered random seed the backend was spawned with.
    fold_index : int
        Zero-based index of the executed OOF fold in the manifest.
    test_pair_ids : tuple of tuple of str
        The fold's held-out TEST pair IDs (the OOF measurement targets).
    predictions : Mapping of (str, str) to numpy.ndarray
        The response-space prediction vector for each held-out TEST pair, keyed by
        canonical pair ID; every vector has length ``response_dim``.
    worker_sha256 : str
        The worker-script digest reported by the post-predict manifest.
    payload_sha256 : str
        The configured fit-role payload digest reported by the post-predict manifest.
    checkpoint_sha256 : str
        The verified checkpoint-file digest from the execution manifest.
    request_sha256 : str
        The order-sensitive combined-request digest from the execution manifest.
    """

    method: str
    seed: int
    fold_index: int
    test_pair_ids: tuple[tuple[str, str], ...]
    predictions: Mapping[tuple[str, str], np.ndarray]
    worker_sha256: str
    payload_sha256: str
    checkpoint_sha256: str
    request_sha256: str


def restrict_development_store(
    store: DevelopmentOutcomeStore,
    *,
    positions: Sequence[int],
    pair_ids: Sequence[tuple[str, str]],
) -> DevelopmentOutcomeStore:
    """Restrict a development outcome store to a subset of calibration rows.

    Slices ``combo_calibration_eps`` by ``positions`` and rebinds the pair IDs, while
    copying the :class:`~alive.compose.phase2a.OutcomeAccessAudit` verbatim so the
    train-only store preserves the source/manifest/role identity and its
    ``sealed_access_count == 0`` (the dev store has no sealed role by construction).
    The restricted store recomputes its own ``content_checksum`` over the subset.

    Parameters
    ----------
    store : DevelopmentOutcomeStore
        The full development (calibration-only) outcome store.
    positions : sequence of int
        Row positions (into the full calibration order) to retain, in train order.
    pair_ids : sequence of (str, str)
        The canonical pair IDs at ``positions``, aligned one-for-one; bound as the
        restricted store's calibration pair IDs.

    Returns
    -------
    DevelopmentOutcomeStore
        A train-only store aligned with ``pair_ids`` and a subset-scoped checksum.
    """
    pos = [int(i) for i in positions]
    eps = np.asarray(store.combo_calibration_eps, dtype=float)[pos]
    audit = dataclasses.replace(store.access_audit)  # verbatim identity copy
    return DevelopmentOutcomeStore(
        combo_calibration_eps=eps,
        combo_calibration_pair_ids=tuple(tuple(p) for p in pair_ids),
        access_audit=audit,
    )


def _verify_alignment(
    oof_manifest: OOFFoldManifest,
    inputs: Phase2aInputs,
    outcome_store: DevelopmentOutcomeStore,
    fold_index: int,
) -> None:
    """Fail closed unless manifest, inputs and store address the same calibration set.

    Runs BEFORE any fold artifact is created so a misaligned request never writes a
    partial artifact or reaches backend creation (plan Task 3).

    Raises
    ------
    FoldJobError
        On a pair-ID, row-count, fold-parameter or fold-index disagreement.
    """
    cal_ids = tuple(tuple(p) for p in inputs.cal_pair_ids)
    if oof_manifest.calibration_pair_ids != cal_ids:
        raise FoldJobError("OOF manifest calibration pair IDs are not aligned with inputs")
    if outcome_store.combo_calibration_pair_ids != cal_ids:
        raise FoldJobError("development outcome pair IDs are not aligned with inputs")
    n = len(cal_ids)
    lengths = {
        "cal_idx_pairs": len(inputs.cal_idx_pairs),
        "additive_cal": int(np.asarray(inputs.additive_cal).shape[0]),
        "eps_split_a": int(np.asarray(inputs.eps_split_a).shape[0]),
        "eps_split_b": int(np.asarray(inputs.eps_split_b).shape[0]),
        "combo_calibration_eps": int(np.asarray(outcome_store.combo_calibration_eps).shape[0]),
    }
    bad = {name: count for name, count in lengths.items() if count != n}
    if bad:
        raise FoldJobError(f"calibration row alignment mismatch: expected {n}, got {bad}")
    if int(oof_manifest.n_genes) != int(inputs.n_genes):
        raise FoldJobError("OOF manifest n_genes disagrees with inputs.n_genes")
    if int(oof_manifest.n_folds) != int(inputs.n_folds):
        raise FoldJobError("OOF manifest n_folds disagrees with inputs.n_folds")
    if int(oof_manifest.split_seed) != int(inputs.seed):
        raise FoldJobError("OOF manifest split_seed disagrees with inputs.seed")
    if not (0 <= int(fold_index) < len(oof_manifest.folds)):
        raise FoldJobError(
            f"fold_index {fold_index} out of range for {len(oof_manifest.folds)} folds"
        )


def _oof_labels_for_train(
    oof_manifest: OOFFoldManifest,
    train_pair_ids: Sequence[tuple[str, str]],
) -> list[int]:
    """Per-train-pair OOF fold labels cross-checked against the verified manifest.

    A covered train pair (a TEST pair of some OTHER fold) carries that outer fold
    index; a globally-uncovered train pair carries the nonnegative sentinel
    ``n_folds`` ("training-only; never an outer-fold test row"), which the payload-v2
    validator accepts as a nonnegative int. Every label is verified against the
    manifest's coverage before it is emitted (plan Task 3).

    Raises
    ------
    FoldJobError
        On a label that is out of range or inconsistent with the manifest coverage.
    """
    test_fold_of: dict[tuple[str, str], int] = {}
    for record in oof_manifest.folds:
        for pid in record.test_pair_ids:
            test_fold_of[pid] = int(record.fold_index)
    covered = set(oof_manifest.covered_pair_ids)
    n_folds = int(oof_manifest.n_folds)
    labels: list[int] = []
    for pid in train_pair_ids:
        pair = tuple(pid)
        if pair in test_fold_of:
            label = test_fold_of[pair]
            if not (0 <= label < n_folds):
                raise FoldJobError(f"train pair {pair!r} maps to out-of-range fold {label}")
            if pair not in covered:
                raise FoldJobError(f"train pair {pair!r} is test-mapped but not covered")
        else:
            label = n_folds  # training-only sentinel
            if pair in covered:
                raise FoldJobError(f"train pair {pair!r} is covered but has no test fold")
        labels.append(int(label))
    return labels


def _fold_artifact_path(
    fold_artifact_dir: str,
    *,
    method: str,
    seed: int,
    fold_index: int,
    base_sha256: str,
    manifest_checksum: str,
) -> str:
    """Build the write-once fold-artifact path binding method/seed/fold/source/OOF.

    The filename binds ``method``, ``seed``, ``fold_index``, the base (source)
    artifact SHA and the OOF-manifest checksum so distinct jobs never collide and a
    re-run of the same job fails closed on the existing file.
    """
    base_hex = str(base_sha256).split(":", 1)[-1]
    name = (
        f"fold_fit_role__m-{method}__s-{int(seed)}__f-{int(fold_index)}"
        f"__src-{base_hex[:16]}__oof-{str(manifest_checksum)[:16]}.h5ad"
    )
    return os.path.join(os.path.realpath(os.path.abspath(fold_artifact_dir)), name)


def _read_base_source(base_fit_role_spec: FitRoleArtifactSpec):
    """Re-open the validated base fit-role artifact as a re-extraction source.

    Returns the obs identity columns, the allowed-rows-only expression, the gene
    order and the provenance so a fold-scoped extractor can carve a train-only subset
    without ever touching a raw/sealed source. The base artifact only ever held
    control + singles + calibration combos, so no outer-sealed combo can be present.

    Raises
    ------
    FoldJobError
        If the base file's bytes no longer match its spec digest.
    """
    import anndata as ad
    from scipy import sparse

    if _file_sha256(base_fit_role_spec.path) != base_fit_role_spec.sha256:
        raise FoldJobError("base fit-role artifact bytes do not match its spec digest")
    adata = ad.read_h5ad(base_fit_role_spec.path)
    obs_src = [str(s) for s in adata.obs["source_row_id"]]
    obs_pert = [str(p) for p in adata.obs["perturbation"]]
    var_names = [str(v) for v in adata.var_names]
    base_x = sparse.csr_matrix(adata.X)
    provenance = {str(k): str(v) for k, v in dict(adata.uns["provenance"]).items()}
    return obs_src, obs_pert, var_names, base_x, provenance


def _assert_no_forbidden_combo(
    path: str,
    *,
    forbidden_pairs: set[tuple[str, str]],
    combo_sep: str,
) -> None:
    """Independently prove no held-out/excluded combo token survived into the artifact.

    Re-opens the written fold artifact and canonicalizes every combo obs token; a
    token whose pair is in ``forbidden_pairs`` (the fold's TEST ∪ EXCLUDED set) fails
    closed. This is defense-in-depth on top of the extractor's sealed-exclusion.

    Raises
    ------
    FoldJobError
        If any forbidden combo token is present.
    """
    import anndata as ad

    adata = ad.read_h5ad(path)
    for token in (str(p) for p in adata.obs["perturbation"]):
        if combo_sep in token and token != _CONTROL_TOKEN:
            a, b = token.split(combo_sep, 1)
            pair = (a, b) if a.encode("utf-8") <= b.encode("utf-8") else (b, a)
            if pair in forbidden_pairs:
                raise FoldJobError(
                    f"fold-scoped fit-role artifact contains forbidden combo {pair!r}"
                )


def build_fold_job(
    *,
    method: str,
    seed: int,
    fold_index: int,
    oof_manifest: OOFFoldManifest,
    inputs: Phase2aInputs,
    outcome_store: DevelopmentOutcomeStore,
    response_artifact: Mapping[str, object],
    base_fit_role_spec: FitRoleArtifactSpec,
    fold_artifact_dir: str,
    gene_order: Sequence[str],
    raw_data_sha256: str,
    control_token: str = _CONTROL_TOKEN,
    combo_sep: str = _COMBO_SEP,
) -> FoldJob:
    """Assemble a leakage-safe, fold-scoped fit job for one gene-disjoint OOF fold.

    For the requested fold this: (1) verifies manifest/input/store alignment BEFORE
    any artifact creation; (2) slices the calibration design to the fold's TRAIN
    positions; (3) writes a new write-once fold-scoped fit-role artifact holding all
    registered control + single rows but only this fold's TRAIN combo rows, validates
    it, and proves no held-out/excluded combo survived; (4) builds a train-only
    development outcome store with a copied audit; (5) calls
    :func:`~alive.compose.phase2a.build_subprocess_fit_payload` ONCE with the
    fold-scoped :class:`~alive.compose.fit_role.FitRoleArtifactSpec`, leaving the
    payload key set exactly :data:`_REQUIRED_KEYS`; and (6) stores every piece of fold
    metadata on the returned :class:`FoldJob`, never inside the payload.

    It opens NO seal and reads NO sealed outcome.

    Parameters
    ----------
    method : str
        The seed-refittable comparator name (``"gears"`` / ``"cpa"``).
    seed : int
        The registered random seed bound into the job and the worker payload.
    fold_index : int
        Zero-based OOF fold index into ``oof_manifest.folds``.
    oof_manifest : OOFFoldManifest
        The verified single-call OOF fold manifest (loaded + validated upstream).
    inputs : Phase2aInputs
        The development inputs; ``response_space_checksum`` must equal the verified
        response-artifact digest so the payload projection binds.
    outcome_store : DevelopmentOutcomeStore
        The full development (calibration-only) outcome store, aligned with
        ``inputs.cal_pair_ids``.
    response_artifact : Mapping
        ``{"response_space", "control_mean"}`` for the payload projection.
    base_fit_role_spec : FitRoleArtifactSpec
        The validated base fit-role artifact (control + singles + every calibration
        combo). It is NEVER handed to a worker during D2 — it would leak outer-fold
        test targets — but it is the source the fold subset is carved from.
    fold_artifact_dir : str
        Approved directory the write-once fold artifact is written into.
    gene_order : sequence of str
        Canonical full transcriptome gene order (must equal the artifacts' var_names).
    raw_data_sha256 : str
        Shared raw-data digest bound across the artifact, projection and source.
    control_token : str, optional
        Obs token denoting a control cell (A1 default ``"control"``).
    combo_sep : str, optional
        Separator between the two single-gene tokens of a combo (A1 default ``"_"``).

    Returns
    -------
    FoldJob
        The fold-scoped job with a payload restricted to the fold's train pairs.

    Raises
    ------
    FoldJobError
        On any alignment, artifact-write, validation or leakage-proof violation.
    """
    _verify_alignment(oof_manifest, inputs, outcome_store, fold_index)

    record = oof_manifest.folds[int(fold_index)]
    cal_ids = tuple(tuple(p) for p in inputs.cal_pair_ids)
    train_pos = [int(i) for i in record.train_pair_positions]
    train_pairs = tuple(cal_ids[i] for i in train_pos)
    if train_pairs != record.train_pair_ids:
        raise FoldJobError("fold train positions disagree with the manifest train pair IDs")
    if not train_pairs:
        raise FoldJobError(f"fold {fold_index} has an empty train set")
    test_pairs = tuple(tuple(p) for p in record.test_pair_ids)
    excluded_pairs = tuple(tuple(p) for p in record.excluded_pair_ids)
    sealed_pairs = test_pairs + excluded_pairs

    # -- fold-scoped fit-role artifact: train combos only; test/excluded excluded ---
    obs_src, obs_pert, var_names, base_x, provenance = _read_base_source(base_fit_role_spec)

    def _row_reader(idx: list[int]):
        return base_x[idx]

    extractor = ComposeFitRoleExtractor(
        obs_source_row_id=obs_src,
        obs_perturbation=obs_pert,
        var_names=var_names,
        calibration_pair_ids=train_pairs,
        sealed_pair_ids=sealed_pairs,
        control_token=control_token,
        raw_data_sha256=provenance["raw_data_sha256"],
        pair_manifest_sha256=provenance["pair_manifest_sha256"],
        eligibility_hash=provenance["eligibility_hash"],
        row_reader=_row_reader,
        combo_sep=combo_sep,
    )
    extraction = extract_fit_roles(extractor=extractor)

    fold_path = _fold_artifact_path(
        fold_artifact_dir,
        method=method,
        seed=seed,
        fold_index=fold_index,
        base_sha256=base_fit_role_spec.sha256,
        manifest_checksum=oof_manifest.manifest_checksum,
    )
    os.makedirs(os.path.dirname(fold_path), exist_ok=True)
    try:
        fold_spec = generate_fit_role_artifact(
            extraction=extraction,
            out_path=fold_path,
            config_sha256=provenance["config_sha256"],
            data_card_sha256=provenance["data_card_sha256"],
            calibration_gene_set_hash=provenance["calibration_gene_set_hash"],
            generator_code_sha256=provenance["generator_code_sha256"],
            writer_environment_sha256=provenance["writer_environment_sha256"],
        )
    except Exception as exc:  # fail closed (write-once collision, invalid extraction)
        raise FoldJobError(f"failed to write fold-scoped fit-role artifact: {exc}") from exc

    single_universe = tuple(sorted(inputs.delta_by_gene, key=lambda g: str(g).encode("utf-8")))
    try:
        validate_fit_role_artifact(
            fold_spec.path,
            spec=fold_spec,
            approved_root=os.path.realpath(os.path.abspath(fold_artifact_dir)),
            calibration_pair_ids=train_pairs,
            sealed_pair_ids=sealed_pairs,
            single_gene_ids=single_universe,
            control_token=control_token,
            combo_sep=combo_sep,
        )
    except Exception as exc:  # fail closed on any validation failure
        raise FoldJobError(f"fold-scoped fit-role artifact failed validation: {exc}") from exc
    _assert_no_forbidden_combo(
        fold_spec.path, forbidden_pairs=set(sealed_pairs), combo_sep=combo_sep
    )

    # -- train-only inputs + development store + per-train-pair OOF labels ----------
    train_inputs = dataclasses.replace(
        inputs,
        seed=int(seed),
        cal_pair_ids=train_pairs,
        cal_idx_pairs=tuple(tuple(inputs.cal_idx_pairs[i]) for i in train_pos),
        additive_cal=np.asarray(inputs.additive_cal, dtype=float)[train_pos],
        eps_split_a=np.asarray(inputs.eps_split_a, dtype=float)[train_pos],
        eps_split_b=np.asarray(inputs.eps_split_b, dtype=float)[train_pos],
    )
    train_store = restrict_development_store(
        outcome_store, positions=train_pos, pair_ids=train_pairs
    )
    oof_labels = _oof_labels_for_train(oof_manifest, train_pairs)

    payload = build_subprocess_fit_payload(
        inputs=train_inputs,
        outcome_store=train_store,
        response_artifact=response_artifact,
        oof_folds=oof_labels,
        fit_role_spec=fold_spec,
        gene_order=gene_order,
        raw_data_sha256=raw_data_sha256,
    )
    if set(payload) != set(_REQUIRED_KEYS):
        raise FoldJobError("fold payload key set drifted from the required payload-v2 roster")

    return FoldJob(
        method=str(method),
        seed=int(seed),
        fold_index=int(fold_index),
        payload=payload,
        test_pair_ids=test_pairs,
        excluded_pair_ids=excluded_pairs,
        fit_role_artifact_path=fold_spec.path,
        fit_role_artifact_sha256=fold_spec.sha256,
        train_source_checksum=train_store.content_checksum,
        fold_manifest_checksum=oof_manifest.manifest_checksum,
    )


def _fold_training_context(
    job: FoldJob,
    *,
    pair_manifest_checksum: str,
    response_space_checksum: str,
) -> BaselineTrainingContext:
    """Build the fold's frozen development-role context from the job's TRAIN pairs.

    The context carries identities and checksums only (no outcome handle, no
    sealed path): the allowed adapter roles, the caller-bound manifest/response
    checksums, this fold's TRAIN pair IDs (``payload["calibration_pair_ids"]``) and
    the fitting single-gene universe (``payload["single_gene_ids"]``).

    Parameters
    ----------
    job : FoldJob
        The fold-scoped job whose payload supplies the fold's TRAIN identities.
    pair_manifest_checksum : str
        The bound pair-split manifest checksum (``inputs.manifest_checksum``).
    response_space_checksum : str
        The bound response-space checksum (``inputs.response_space_checksum``).

    Returns
    -------
    BaselineTrainingContext
        The frozen context handed to the guarded adapter for this fold.
    """
    return BaselineTrainingContext(
        allowed_roles=frozenset({"singles", "combo_calibration"}),
        pair_manifest_checksum=str(pair_manifest_checksum),
        response_space_checksum=str(response_space_checksum),
        training_pair_ids=tuple(tuple(p) for p in job.payload["calibration_pair_ids"]),
        single_gene_ids=tuple(str(g) for g in job.payload["single_gene_ids"]),
    )


def run_fold_job(
    adapter: object,
    job: FoldJob,
    response_dim: int,
    *,
    pair_manifest_checksum: str,
    response_space_checksum: str,
) -> FoldExecutionResult:
    """Execute ONE isolated ``(method, seed, fold)`` job on a fresh backend.

    Runs the full per-fold seam exactly once, without ever pre-building a
    cross-fold context map (which would leave one shared backend configured to the
    last fold): spawn a fresh seed-bound backend, configure it with the fold's
    TRAIN-only payload, build the fold's development-role context, predict ONLY the
    fold's held-out TEST pairs a single time, then read the backend's post-predict
    ``provenance_manifest`` and capture the *real* worker / payload / checkpoint /
    request digests it reports. It opens NO seal and reads NO sealed outcome.

    Parameters
    ----------
    adapter : object
        A spawnable guarded baseline adapter (``adapter.spawn(seed=...)`` returns a
        fresh adapter wrapping a fresh, unconfigured backend). A subprocess GEARS /
        CPA adapter in production; a deterministic seam-compatible stub in tests.
    job : FoldJob
        The fold-scoped job to execute (payload restricted to the fold's TRAIN
        pairs; TEST/EXCLUDED pairs absent).
    response_dim : int
        The required response dimension for every prediction vector.
    pair_manifest_checksum : str
        The bound pair-split manifest checksum for the fold context
        (``inputs.manifest_checksum``).
    response_space_checksum : str
        The bound response-space checksum for the fold context
        (``inputs.response_space_checksum``).

    Returns
    -------
    FoldExecutionResult
        The fold's held-out TEST-pair predictions plus the real provenance digests.

    Raises
    ------
    FoldExecutionError
        If the backend's ``provenance_manifest`` is not in its post-predict form
        (no verified ``execution_manifest``), so no real checkpoint/request digest
        can be captured.
    """
    fold_adapter = adapter.spawn(seed=job.seed)
    backend = fold_adapter.backend
    backend.configure_payload(job.payload)
    context = _fold_training_context(
        job,
        pair_manifest_checksum=pair_manifest_checksum,
        response_space_checksum=response_space_checksum,
    )
    predictions = fold_adapter.predict(context, list(job.test_pair_ids), int(response_dim))

    manifest = backend.provenance_manifest
    if "execution_manifest" not in manifest:
        raise FoldExecutionError(
            f"{job.method} backend provenance manifest is not in its post-predict form; "
            "no verified checkpoint/request digest is available"
        )
    execution_manifest = manifest["execution_manifest"]
    return FoldExecutionResult(
        method=str(job.method),
        seed=int(job.seed),
        fold_index=int(job.fold_index),
        test_pair_ids=tuple(tuple(p) for p in job.test_pair_ids),
        predictions={tuple(k): np.asarray(v, dtype=float) for k, v in predictions.items()},
        worker_sha256=str(manifest["worker_sha256"]),
        payload_sha256=str(manifest["payload_sha256"]),
        checkpoint_sha256=str(execution_manifest["checkpoint_sha256"]),
        request_sha256=str(execution_manifest["combined_request_sha256"]),
    )


def assemble_seed_scalar(
    fold_results: Sequence[FoldExecutionResult],
    *,
    manifest: OOFFoldManifest,
    delta_truth_by_pair: Mapping[tuple[str, str], np.ndarray],
    response_dim: int,
) -> tuple[dict[tuple[str, str], np.ndarray], float]:
    """Reassemble one seed's fold predictions into a covered-order OOF scalar.

    Concatenates every fold's held-out TEST predictions and requires the covered
    set — ``manifest.covered_pair_ids`` — to be predicted EXACTLY once: a missing,
    duplicate, extra, non-finite or dimension-mismatched prediction makes the whole
    seed fail (raises), never a partial or imputed result. The surviving
    predictions are reordered to the manifest's fixed covered order and scored
    against the development delta with per-pair MSE
    ``mean((pred - delta_truth) ** 2)`` over response dims; the returned scalar is
    the mean over the fixed covered set.

    Parameters
    ----------
    fold_results : sequence of FoldExecutionResult
        The per-fold execution results for a single seed (any order).
    manifest : OOFFoldManifest
        The verified OOF fold manifest; its ``covered_pair_ids`` fix both the
        required coverage and the canonical output order.
    delta_truth_by_pair : Mapping of (str, str) to numpy.ndarray
        The development delta (``inputs.additive_cal + combo_calibration_eps``)
        pair-aligned, reconstructed once by the caller. Must cover every covered pair.
    response_dim : int
        The required length of every prediction and delta-truth vector.

    Returns
    -------
    tuple of (dict of (str, str) to numpy.ndarray, float)
        ``(pred_by_pair, mean_pair_mse)`` where ``pred_by_pair`` is in the
        manifest's covered order and ``mean_pair_mse`` is the per-seed scalar.

    Raises
    ------
    SeedAssemblyError
        On empty coverage, or any missing / duplicate / extra / non-finite /
        dimension-mismatched prediction, or a covered pair lacking a delta truth.
    """
    covered = tuple(tuple(p) for p in manifest.covered_pair_ids)
    if not covered:
        raise SeedAssemblyError("manifest has no covered pairs to reassemble")
    dim = int(response_dim)
    covered_set = set(covered)

    pred_by_pair: dict[tuple[str, str], np.ndarray] = {}
    for result in fold_results:
        for raw_pair, raw_vec in result.predictions.items():
            pair = tuple(raw_pair)
            if pair in pred_by_pair:
                raise SeedAssemblyError(f"duplicate prediction for covered pair {pair!r}")
            arr = np.asarray(raw_vec, dtype=float)
            if arr.shape != (dim,):
                raise SeedAssemblyError(
                    f"prediction for {pair!r} has shape {arr.shape}, expected ({dim},)"
                )
            if not np.all(np.isfinite(arr)):
                raise SeedAssemblyError(f"prediction for {pair!r} contains non-finite values")
            pred_by_pair[pair] = arr

    missing = covered_set - set(pred_by_pair)
    if missing:
        raise SeedAssemblyError(f"missing predictions for covered pairs: {sorted(missing)}")
    extra = set(pred_by_pair) - covered_set
    if extra:
        raise SeedAssemblyError(f"predictions for non-covered pairs: {sorted(extra)}")

    ordered: dict[tuple[str, str], np.ndarray] = {}
    per_pair_mse: list[float] = []
    for pair in covered:
        if pair not in delta_truth_by_pair:
            raise SeedAssemblyError(f"no development delta truth for covered pair {pair!r}")
        truth = np.asarray(delta_truth_by_pair[pair], dtype=float)
        if truth.shape != (dim,):
            raise SeedAssemblyError(
                f"delta truth for {pair!r} has shape {truth.shape}, expected ({dim},)"
            )
        pred = pred_by_pair[pair]
        ordered[pair] = pred
        per_pair_mse.append(float(np.mean((pred - truth) ** 2)))

    return ordered, float(np.mean(per_pair_mse))


# =========================================================================== #
# D2 Task 5 — strict report containers + the production orchestration entry
# =========================================================================== #
#
# ``development_seed_variability`` is the TOP-LEVEL D2 entry: it ties Tasks 1-4
# together (OOF fold manifest -> per-(method, seed, fold) fold jobs -> isolated
# fold execution -> covered-order per-seed OOF scalar) into a strict, self-checked
# :class:`SeedVariabilityReport`. It opens NO seal and reads NO sealed outcome;
# it measures ONLY development-calibration seed-to-seed dispersion of the two
# refittable comparators ({gears, cpa}).

#: Immutable schema tag for the persisted seed-variability report.
_SEED_VARIABILITY_REPORT_SCHEMA = "compose_seed_variability_report_v1"

#: The two comparators refit once per registered seed inside the D2 seed loop.
#: Everything else in the config method roster is the DETERMINISTIC single-shot
#: roster: recorded in the report for provenance but never entered into the loop.
_SEED_LOOP_ROSTER: frozenset[str] = frozenset({"gears", "cpa"})

#: Subdirectory (beside the base fit-role artifact) the write-once fold-scoped
#: fit-role artifacts are written into. Derived rather than passed so the entry
#: keeps its declared signature; the fold artifacts are development derivatives of
#: the base fit-role artifact and belong next to it (CLAUDE.md §12 ``artifacts/``).
_FOLD_ARTIFACT_SUBDIR = "d2_seed_variability_folds"

#: Top-level keys of a serialised :class:`SeedVariabilityReport` (exact set).
_REPORT_KEYS: frozenset[str] = frozenset(
    {
        "schema",
        "protocol",
        "run_id",
        "config_sha256",
        "registered_seeds",
        "deterministic_roster",
        "oof_manifest_checksum",
        "coverage",
        "response_space_checksum",
        "base_fit_role_artifact_sha256",
        "fold_fit_role_artifact_sha256s",
        "dev_store_content_checksum",
        "worker_locks",
        "summaries",
        "fold_execution_records",
        "status",
        "report_checksum",
    }
)


class SeedVariabilityContractError(ValueError):
    """Raised on a whole-call D2 contract/provenance violation.

    Covers the store-type gate (a non-:class:`DevelopmentOutcomeStore` such as a
    sealed :class:`~alive.compose.outcome_store.ComposeOutcomeStore`, an array, a
    dict, a path or an arbitrary object), an adapter roster that is not exactly
    ``{"gears", "cpa"}``, a config↔manifest↔inputs inequality (split seed, fold
    count, registered seeds, tolerance), a pair-ID misalignment, and a development
    outcome store whose ``content_checksum`` no longer verifies. Every such
    violation FAILS THE WHOLE CALL — it is never laundered into a failed-seed
    result.
    """


class SeedVariabilityReportError(ValueError):
    """Raised on an invalid, non-finite or tampered :class:`SeedVariabilityReport`.

    Covers a wrong schema tag, a non-:class:`SeedVariabilityStatus` status, a
    non-finite float anywhere in the report, a write-once collision, and a
    self-excluding-checksum mismatch on load (tampering).
    """


class SeedVariabilityStatus(str, Enum):
    """Terminal status of a seed-variability run.

    ``COMPLETE`` requires every seed of every stochastic method to succeed AND the
    uncovered fraction to stay within tolerance. Any failed seed, an out-of-tolerance
    uncovered fraction, or a non-finite per-seed statistic yields ``INCOMPLETE``.
    """

    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


def _finite(value: object, *, field_name: str) -> float:
    """Return ``value`` as a finite float or raise :class:`SeedVariabilityReportError`."""
    if isinstance(value, bool) or not isinstance(value, (int, float, np.floating, np.integer)):
        raise SeedVariabilityReportError(f"{field_name} must be a finite float, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise SeedVariabilityReportError(f"{field_name} must be finite, got {number!r}")
    return number


def _predictions_checksum(predictions: Mapping[tuple[str, str], np.ndarray]) -> str:
    """Canonical SHA-256 digest of a fold's covered (held-out TEST) predictions.

    Parameters
    ----------
    predictions : Mapping of (str, str) to numpy.ndarray
        The fold's held-out TEST-pair prediction vectors keyed by canonical pair ID.

    Returns
    -------
    str
        A canonical, order-independent 64-hex digest of the predictions.
    """
    payload = {
        f"{a}|{b}": np.asarray(vec, dtype=float).tolist()
        for (a, b), vec in sorted(predictions.items())
    }
    return sha256_json(payload)


@dataclass(frozen=True)
class CoverageReport:
    """OOF coverage of the development calibration pairs (strict, finite).

    Attributes
    ----------
    total_pairs : int
        Number of development calibration pairs.
    covered_count, uncovered_count : int
        Counts of pairs that are (respectively are not) some fold's OOF TEST pair.
    covered_fraction, uncovered_fraction : float
        The corresponding fractions of ``total_pairs``.
    covered_pair_ids_checksum, uncovered_pair_ids_checksum : str
        Canonical digests of the ordered covered / uncovered pair-ID lists (in the
        manifest's fixed order), so coverage identity is bound without inlining IDs.
    uncovered_tolerance : float
        The pre-registered maximum uncovered fraction (config value).
    """

    total_pairs: int
    covered_count: int
    uncovered_count: int
    covered_fraction: float
    uncovered_fraction: float
    covered_pair_ids_checksum: str
    uncovered_pair_ids_checksum: str
    uncovered_tolerance: float

    def to_dict(self) -> dict:
        """Return a canonical JSON-serialisable representation."""
        return {
            "total_pairs": int(self.total_pairs),
            "covered_count": int(self.covered_count),
            "uncovered_count": int(self.uncovered_count),
            "covered_fraction": _finite(self.covered_fraction, field_name="covered_fraction"),
            "uncovered_fraction": _finite(self.uncovered_fraction, field_name="uncovered_fraction"),
            "covered_pair_ids_checksum": str(self.covered_pair_ids_checksum),
            "uncovered_pair_ids_checksum": str(self.uncovered_pair_ids_checksum),
            "uncovered_tolerance": _finite(
                self.uncovered_tolerance, field_name="uncovered_tolerance"
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> CoverageReport:
        """Reconstruct a :class:`CoverageReport` from :meth:`to_dict` output."""
        return cls(
            total_pairs=int(data["total_pairs"]),
            covered_count=int(data["covered_count"]),
            uncovered_count=int(data["uncovered_count"]),
            covered_fraction=float(data["covered_fraction"]),
            uncovered_fraction=float(data["uncovered_fraction"]),
            covered_pair_ids_checksum=str(data["covered_pair_ids_checksum"]),
            uncovered_pair_ids_checksum=str(data["uncovered_pair_ids_checksum"]),
            uncovered_tolerance=float(data["uncovered_tolerance"]),
        )


@dataclass(frozen=True)
class FoldExecutionRecord:
    """Real provenance digests captured from ONE executed ``(method, seed, fold)`` job.

    Every digest is the value the backend's post-predict ``provenance_manifest``
    (or the fold job) actually reported — never a value synthesized from
    ``{method, seed}``.

    Attributes
    ----------
    method : str
        The refittable comparator name (``"gears"`` / ``"cpa"``).
    seed : int
        The registered seed the backend was spawned with.
    fold : int
        Zero-based OOF fold index.
    fold_fit_role_artifact_sha256 : str
        The fold-scoped fit-role artifact digest (from the fold job).
    payload_sha256 : str
        The configured fit-role payload digest reported by the backend.
    request_sha256 : str
        The order-sensitive combined-request digest reported by the backend.
    checkpoint_sha256 : str
        The verified checkpoint-file digest reported by the backend.
    predictions_sha256 : str
        Canonical digest of the fold's covered (held-out TEST) predictions.
    worker_identity_sha256 : str
        The worker-script / identity-lock digest reported by the backend.
    """

    method: str
    seed: int
    fold: int
    fold_fit_role_artifact_sha256: str
    payload_sha256: str
    request_sha256: str
    checkpoint_sha256: str
    predictions_sha256: str
    worker_identity_sha256: str

    def to_dict(self) -> dict:
        """Return a canonical JSON-serialisable representation."""
        return {
            "method": str(self.method),
            "seed": int(self.seed),
            "fold": int(self.fold),
            "fold_fit_role_artifact_sha256": str(self.fold_fit_role_artifact_sha256),
            "payload_sha256": str(self.payload_sha256),
            "request_sha256": str(self.request_sha256),
            "checkpoint_sha256": str(self.checkpoint_sha256),
            "predictions_sha256": str(self.predictions_sha256),
            "worker_identity_sha256": str(self.worker_identity_sha256),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> FoldExecutionRecord:
        """Reconstruct a :class:`FoldExecutionRecord` from :meth:`to_dict` output."""
        return cls(
            method=str(data["method"]),
            seed=int(data["seed"]),
            fold=int(data["fold"]),
            fold_fit_role_artifact_sha256=str(data["fold_fit_role_artifact_sha256"]),
            payload_sha256=str(data["payload_sha256"]),
            request_sha256=str(data["request_sha256"]),
            checkpoint_sha256=str(data["checkpoint_sha256"]),
            predictions_sha256=str(data["predictions_sha256"]),
            worker_identity_sha256=str(data["worker_identity_sha256"]),
        )


@dataclass(frozen=True)
class SeedComparatorSummary:
    """Per-method seed-dispersion summary of the per-seed OOF-MSE scalars.

    Attributes
    ----------
    method : str
        The refittable comparator name (``"gears"`` / ``"cpa"``).
    oof_mse_by_seed : Mapping of int to float
        Per-seed covered-order OOF-MSE, SUCCESSFUL seeds only, in registered-seed
        order. A failed seed is absent here (but retained in ``failed_seeds``).
    mean, sample_std, minimum, maximum, value_range : float
        Dispersion statistics over the successful seeds. ``sample_std`` uses
        ``ddof=1`` and is ``0.0`` when fewer than two seeds succeeded; all five are
        ``0.0`` when no seed succeeded (the run is then ``INCOMPLETE``).
    failed_seeds : tuple of int
        Registered seeds whose execution failed, in registered-seed order (never
        dropped from the roster).
    failure_class_by_seed : Mapping of int to str
        Scrubbed exception CLASS name (no message/data) per failed seed.
    fold_execution_records : tuple of FoldExecutionRecord
        The real per-fold provenance records this method produced (across seeds).
    """

    method: str
    oof_mse_by_seed: Mapping[int, float]
    mean: float
    sample_std: float
    minimum: float
    maximum: float
    value_range: float
    failed_seeds: tuple[int, ...]
    failure_class_by_seed: Mapping[int, str]
    fold_execution_records: tuple[FoldExecutionRecord, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "oof_mse_by_seed",
            {int(s): float(v) for s, v in dict(self.oof_mse_by_seed).items()},
        )
        object.__setattr__(self, "failed_seeds", tuple(int(s) for s in self.failed_seeds))
        object.__setattr__(
            self,
            "failure_class_by_seed",
            {int(s): str(c) for s, c in dict(self.failure_class_by_seed).items()},
        )
        object.__setattr__(self, "fold_execution_records", tuple(self.fold_execution_records))

    def to_dict(self) -> dict:
        """Return a canonical JSON-serialisable representation (finite floats only)."""
        return {
            "method": str(self.method),
            "oof_mse_by_seed": [
                [int(s), _finite(v, field_name=f"{self.method} oof_mse[{s}]")]
                for s, v in self.oof_mse_by_seed.items()
            ],
            "mean": _finite(self.mean, field_name=f"{self.method} mean"),
            "sample_std": _finite(self.sample_std, field_name=f"{self.method} sample_std"),
            "minimum": _finite(self.minimum, field_name=f"{self.method} minimum"),
            "maximum": _finite(self.maximum, field_name=f"{self.method} maximum"),
            "value_range": _finite(self.value_range, field_name=f"{self.method} value_range"),
            "failed_seeds": [int(s) for s in self.failed_seeds],
            "failure_class_by_seed": [
                [int(s), str(c)] for s, c in self.failure_class_by_seed.items()
            ],
            "fold_execution_records": [r.to_dict() for r in self.fold_execution_records],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> SeedComparatorSummary:
        """Reconstruct a :class:`SeedComparatorSummary` from :meth:`to_dict` output."""
        return cls(
            method=str(data["method"]),
            oof_mse_by_seed={int(s): float(v) for s, v in data["oof_mse_by_seed"]},
            mean=float(data["mean"]),
            sample_std=float(data["sample_std"]),
            minimum=float(data["minimum"]),
            maximum=float(data["maximum"]),
            value_range=float(data["value_range"]),
            failed_seeds=tuple(int(s) for s in data["failed_seeds"]),
            failure_class_by_seed={int(s): str(c) for s, c in data["failure_class_by_seed"]},
            fold_execution_records=tuple(
                FoldExecutionRecord.from_dict(r) for r in data["fold_execution_records"]
            ),
        )


@dataclass(frozen=True)
class SeedVariabilityReport:
    """Strict, self-checksummed record of one D2 seed-variability run.

    Binds the protocol, run ID, config digest, registered seed order, the
    deterministic (single-shot) roster, the OOF fold-manifest checksum, the
    coverage report, the response-space checksum, the base fit-role artifact
    digest, EVERY fold-scoped fit-role artifact digest, the development outcome
    store's content checksum, the distinct worker-identity locks, every real
    :class:`FoldExecutionRecord` and the terminal status. Schema is validated,
    all floats must be finite, and :attr:`report_checksum` is a self-excluding
    SHA-256 over :meth:`_payload` so any content change moves it and :meth:`load`
    fails closed on tampering.
    """

    schema: str
    protocol: str
    run_id: str
    config_sha256: str
    registered_seeds: tuple[int, ...]
    deterministic_roster: tuple[str, ...]
    oof_manifest_checksum: str
    coverage: CoverageReport
    response_space_checksum: str
    base_fit_role_artifact_sha256: str
    fold_fit_role_artifact_sha256s: tuple[str, ...]
    dev_store_content_checksum: str
    worker_locks: tuple[str, ...]
    summaries: tuple[SeedComparatorSummary, ...]
    fold_execution_records: tuple[FoldExecutionRecord, ...]
    status: SeedVariabilityStatus
    report_checksum: str = field(default="")

    def __post_init__(self) -> None:
        if self.schema != _SEED_VARIABILITY_REPORT_SCHEMA:
            raise SeedVariabilityReportError(f"unexpected report schema {self.schema!r}")
        if not isinstance(self.status, SeedVariabilityStatus):
            raise SeedVariabilityReportError(
                f"status must be a SeedVariabilityStatus, got {self.status!r}"
            )
        object.__setattr__(self, "registered_seeds", tuple(int(s) for s in self.registered_seeds))
        object.__setattr__(
            self, "deterministic_roster", tuple(str(m) for m in self.deterministic_roster)
        )
        object.__setattr__(
            self,
            "fold_fit_role_artifact_sha256s",
            tuple(str(s) for s in self.fold_fit_role_artifact_sha256s),
        )
        object.__setattr__(self, "worker_locks", tuple(str(w) for w in self.worker_locks))
        object.__setattr__(self, "summaries", tuple(self.summaries))
        object.__setattr__(self, "fold_execution_records", tuple(self.fold_execution_records))
        # Finiteness is validated as part of building the canonical payload
        # (``to_dict`` on coverage / summaries raises on any NaN/Inf), and the
        # self-excluding checksum is computed over that payload.
        object.__setattr__(self, "report_checksum", sha256_json(self._payload()))

    # -- canonical payload + serialisation -------------------------------- #
    def _payload(self) -> dict:
        """Canonical checksum input (every field EXCEPT ``report_checksum``)."""
        return {
            "schema": self.schema,
            "protocol": self.protocol,
            "run_id": self.run_id,
            "config_sha256": self.config_sha256,
            "registered_seeds": [int(s) for s in self.registered_seeds],
            "deterministic_roster": [str(m) for m in self.deterministic_roster],
            "oof_manifest_checksum": self.oof_manifest_checksum,
            "coverage": self.coverage.to_dict(),
            "response_space_checksum": self.response_space_checksum,
            "base_fit_role_artifact_sha256": self.base_fit_role_artifact_sha256,
            "fold_fit_role_artifact_sha256s": [str(s) for s in self.fold_fit_role_artifact_sha256s],
            "dev_store_content_checksum": self.dev_store_content_checksum,
            "worker_locks": [str(w) for w in self.worker_locks],
            "summaries": [s.to_dict() for s in self.summaries],
            "fold_execution_records": [r.to_dict() for r in self.fold_execution_records],
            "status": self.status.value,
        }

    def to_dict(self) -> dict:
        """Return the canonical payload augmented with the self-excluding checksum."""
        payload = self._payload()
        payload["report_checksum"] = self.report_checksum
        return payload

    def write_once(self, path: str | Path) -> None:
        """Serialise the report to ``path`` as canonical JSON (write-once).

        Parameters
        ----------
        path : str or Path
            Destination file; must not already exist (write-once, CLAUDE.md §11).

        Raises
        ------
        SeedVariabilityReportError
            If ``path`` already exists.
        """
        try:
            atomic_write_once(
                path, json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
            )
        except FileExistsError as exc:
            raise SeedVariabilityReportError(
                f"refusing to overwrite existing seed-variability report at {path}: write-once"
            ) from exc

    @classmethod
    def load(cls, path: str | Path) -> SeedVariabilityReport:
        """Load and fully VERIFY a report written by :meth:`write_once`.

        Fails closed (:class:`SeedVariabilityReportError`) on unknown/missing keys,
        a wrong schema tag, an unknown status, a non-finite float, or a
        self-excluding-checksum mismatch (tampering).

        Parameters
        ----------
        path : str or Path
            Path to a report JSON file.

        Returns
        -------
        SeedVariabilityReport
            The verified report (its recorded checksum matches the recomputation).
        """
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise SeedVariabilityReportError(f"failed to read report: {exc}") from exc
        if not isinstance(data, dict):
            raise SeedVariabilityReportError("report root must be a JSON object")
        keys = set(data)
        if keys != set(_REPORT_KEYS):
            raise SeedVariabilityReportError(
                f"report key set mismatch (missing={sorted(_REPORT_KEYS - keys)}, "
                f"unknown={sorted(keys - _REPORT_KEYS)})"
            )
        try:
            status = SeedVariabilityStatus(data["status"])
        except ValueError as exc:
            raise SeedVariabilityReportError(f"unknown status {data['status']!r}") from exc

        report = cls(
            schema=str(data["schema"]),
            protocol=str(data["protocol"]),
            run_id=str(data["run_id"]),
            config_sha256=str(data["config_sha256"]),
            registered_seeds=tuple(int(s) for s in data["registered_seeds"]),
            deterministic_roster=tuple(str(m) for m in data["deterministic_roster"]),
            oof_manifest_checksum=str(data["oof_manifest_checksum"]),
            coverage=CoverageReport.from_dict(data["coverage"]),
            response_space_checksum=str(data["response_space_checksum"]),
            base_fit_role_artifact_sha256=str(data["base_fit_role_artifact_sha256"]),
            fold_fit_role_artifact_sha256s=tuple(
                str(s) for s in data["fold_fit_role_artifact_sha256s"]
            ),
            dev_store_content_checksum=str(data["dev_store_content_checksum"]),
            worker_locks=tuple(str(w) for w in data["worker_locks"]),
            summaries=tuple(SeedComparatorSummary.from_dict(s) for s in data["summaries"]),
            fold_execution_records=tuple(
                FoldExecutionRecord.from_dict(r) for r in data["fold_execution_records"]
            ),
            status=status,
        )
        stored = data["report_checksum"]
        if not isinstance(stored, str) or stored != report.report_checksum:
            raise SeedVariabilityReportError(
                "report checksum mismatch: content was tampered after sealing"
            )
        return report


# --------------------------------------------------------------------------- #
# orchestration helpers
# --------------------------------------------------------------------------- #


def _fold_artifact_dir(fit_role_spec: FitRoleArtifactSpec) -> str:
    """Return the write-once fold-artifact directory beside the base artifact."""
    base_dir = os.path.dirname(os.path.realpath(os.path.abspath(fit_role_spec.path)))
    return os.path.join(base_dir, _FOLD_ARTIFACT_SUBDIR)


def _verify_orchestration_contract(
    *,
    config: ComposePhase2Config,
    oof_manifest: OOFFoldManifest,
    inputs: Phase2aInputs,
    development_outcome_store: DevelopmentOutcomeStore,
) -> None:
    """Fail the WHOLE CALL unless config, manifest, inputs and store agree.

    Runs before any fold job so a misaligned request never spawns a backend or
    writes a fold artifact. Every disagreement raises
    :class:`SeedVariabilityContractError`; none is laundered into a failed seed.

    Raises
    ------
    SeedVariabilityContractError
        On a pair-ID misalignment, a config↔manifest↔inputs inequality (split
        seed / fold count / registered seeds / tolerance / gene count), or a
        development outcome store whose ``content_checksum`` no longer verifies.
    """
    cal_ids = tuple(tuple(p) for p in inputs.cal_pair_ids)
    if oof_manifest.calibration_pair_ids != cal_ids:
        raise SeedVariabilityContractError(
            "OOF manifest calibration pair IDs are not aligned with inputs.cal_pair_ids"
        )
    if development_outcome_store.combo_calibration_pair_ids != cal_ids:
        raise SeedVariabilityContractError(
            "development outcome pair IDs are not aligned with inputs.cal_pair_ids"
        )

    def _eq(name: str, config_value: int, manifest_value: int, inputs_value: int) -> None:
        if not (int(config_value) == int(manifest_value) == int(inputs_value)):
            raise SeedVariabilityContractError(
                f"{name} disagree: config={config_value}, manifest={manifest_value}, "
                f"inputs={inputs_value}"
            )

    _eq("split seeds", config.split_seed, oof_manifest.split_seed, inputs.seed)
    _eq("fold counts", config.oof_folds, oof_manifest.n_folds, inputs.n_folds)
    _eq("gene counts", int(inputs.n_genes), oof_manifest.n_genes, int(inputs.n_genes))

    if tuple(int(s) for s in config.registered_seeds) != tuple(
        int(s) for s in inputs.registered_seeds
    ):
        raise SeedVariabilityContractError(
            "config.registered_seeds disagree with inputs.registered_seeds"
        )
    if float(config.uncovered_tolerance) != float(inputs.uncovered_tolerance):
        raise SeedVariabilityContractError(
            "config.uncovered_tolerance disagrees with inputs.uncovered_tolerance"
        )
    if _outcome_store_checksum(development_outcome_store) != (
        development_outcome_store.content_checksum
    ):
        raise SeedVariabilityContractError(
            "development outcome store content changed after its checksum was bound"
        )


def _build_delta_truth(
    inputs: Phase2aInputs,
    development_outcome_store: DevelopmentOutcomeStore,
) -> dict[tuple[str, str], np.ndarray]:
    """Reconstruct the development delta ``additive_cal + eps`` once, pair-aligned."""
    cal_ids = tuple(tuple(p) for p in inputs.cal_pair_ids)
    additive = np.asarray(inputs.additive_cal, dtype=float)
    eps = np.asarray(development_outcome_store.combo_calibration_eps, dtype=float)
    if additive.shape[0] != len(cal_ids) or eps.shape[0] != len(cal_ids):
        raise SeedVariabilityContractError(
            "additive_cal / combo_calibration_eps are not aligned with cal_pair_ids"
        )
    delta = additive + eps
    return {cal_ids[i]: delta[i] for i in range(len(cal_ids))}


def _build_coverage(oof_manifest: OOFFoldManifest, *, uncovered_tolerance: float) -> CoverageReport:
    """Build the strict OOF :class:`CoverageReport` from the verified manifest."""
    total = len(oof_manifest.calibration_pair_ids)
    covered = tuple(oof_manifest.covered_pair_ids)
    uncovered = tuple(oof_manifest.uncovered_pair_ids)
    denom = float(total) if total else 1.0
    return CoverageReport(
        total_pairs=int(total),
        covered_count=len(covered),
        uncovered_count=len(uncovered),
        covered_fraction=len(covered) / denom,
        uncovered_fraction=len(uncovered) / denom,
        covered_pair_ids_checksum=sha256_json([list(p) for p in covered]),
        uncovered_pair_ids_checksum=sha256_json([list(p) for p in uncovered]),
        uncovered_tolerance=float(uncovered_tolerance),
    )


def _fold_record(
    method: str, seed: int, job: FoldJob, result: FoldExecutionResult
) -> FoldExecutionRecord:
    """Build a :class:`FoldExecutionRecord` from a job + its real execution result."""
    return FoldExecutionRecord(
        method=str(method),
        seed=int(seed),
        fold=int(job.fold_index),
        fold_fit_role_artifact_sha256=str(job.fit_role_artifact_sha256),
        payload_sha256=str(result.payload_sha256),
        request_sha256=str(result.request_sha256),
        checkpoint_sha256=str(result.checkpoint_sha256),
        predictions_sha256=_predictions_checksum(result.predictions),
        worker_identity_sha256=str(result.worker_sha256),
    )


def _summarize_seed_scalars(
    method: str,
    registered_seeds: Sequence[int],
    *,
    oof_by_seed: Mapping[int, float],
    failed_seeds: Sequence[int],
    failure_class_by_seed: Mapping[int, str],
    fold_records: Sequence[FoldExecutionRecord],
) -> SeedComparatorSummary:
    """Reduce a method's per-seed OOF scalars to a strict dispersion summary.

    ``sample_std`` uses ``ddof=1`` (``0.0`` with fewer than two successful seeds);
    all statistics are ``0.0`` when no seed succeeded (the run is then INCOMPLETE).
    Successful seeds are ordered by the registered-seed order.
    """
    ordered = {
        int(s): float(oof_by_seed[int(s)]) for s in registered_seeds if int(s) in oof_by_seed
    }
    values = list(ordered.values())
    if values:
        mean = float(np.mean(values))
        minimum = float(min(values))
        maximum = float(max(values))
        value_range = maximum - minimum
        sample_std = float(np.std(values, ddof=1)) if len(values) >= 2 else 0.0
    else:
        mean = minimum = maximum = value_range = sample_std = 0.0
    failed_in_order = tuple(int(s) for s in registered_seeds if int(s) in set(failed_seeds))
    return SeedComparatorSummary(
        method=str(method),
        oof_mse_by_seed=ordered,
        mean=mean,
        sample_std=sample_std,
        minimum=minimum,
        maximum=maximum,
        value_range=value_range,
        failed_seeds=failed_in_order,
        failure_class_by_seed={int(s): str(failure_class_by_seed[int(s)]) for s in failed_in_order},
        fold_execution_records=tuple(fold_records),
    )


# --------------------------------------------------------------------------- #
# production entry
# --------------------------------------------------------------------------- #


def development_seed_variability(
    *,
    inputs: Phase2aInputs,
    development_outcome_store: DevelopmentOutcomeStore,
    oof_manifest: OOFFoldManifest,
    baseline_adapters: Mapping[str, BaselineAdapter],
    config: ComposePhase2Config,
    response_artifact: Mapping[str, object],
    fit_role_spec: FitRoleArtifactSpec,
    gene_order: Sequence[str],
    raw_data_sha256: str,
) -> SeedVariabilityReport:
    """Measure development seed-to-seed OOF dispersion of ``{gears, cpa}`` (D2 Task 5).

    For each refittable comparator and each registered seed (in ``config``'s exact
    order), this refits the comparator once per gene-disjoint OOF fold on that
    fold's TRAIN-only pairs, predicts the fold's held-out TEST pairs, and reduces
    the folds to one covered-order per-seed OOF-MSE scalar. It ties together the
    committed Tasks 1-4: :class:`OOFFoldManifest`, :func:`build_fold_job`,
    :func:`run_fold_job` and :func:`assemble_seed_scalar`. The deterministic
    single-shot roster (every other config method) is RECORDED but never entered
    into the seed loop.

    It opens NO seal and reads NO sealed outcome — only the development delta
    ``inputs.additive_cal + development_outcome_store.combo_calibration_eps``.

    The run identity is bound via ``inputs.run_id`` (the composite COMPOSE run ID
    already computed for these inputs) together with the config / manifest /
    response / dev-store checksums; no fake run ID is invented and no explicit
    ``run_id`` kwarg is required (the pre-access ledger identity is a Task-6
    concern).

    Failure policy. An EXPECTED per-job execution failure (a
    :func:`run_fold_job` / :func:`assemble_seed_scalar` raise for one seed) records
    only a SCRUBBED exception class name, keeps the seed in the roster, and marks
    the whole report ``INCOMPLETE``. ``BaseException`` is never caught. Internal
    contract/provenance violations (the store-type gate, an adapter roster that is
    not ``{gears, cpa}``, a config↔manifest↔inputs inequality, a coverage/pair
    misalignment, or a fold-job leakage/contract failure) FAIL THE WHOLE CALL and
    are never laundered into a failed-seed result.

    Parameters
    ----------
    inputs : Phase2aInputs
        The bound development inputs (identities/features only).
    development_outcome_store : DevelopmentOutcomeStore
        The typed calibration-only outcome store. A sealed
        :class:`~alive.compose.outcome_store.ComposeOutcomeStore`, an array, a
        dict, a path or any other object is rejected by the store-type gate.
    oof_manifest : OOFFoldManifest
        The verified single-call OOF fold manifest.
    baseline_adapters : Mapping of str to BaselineAdapter
        Exactly ``{"gears", "cpa"}`` spawnable guarded adapters.
    config : ComposePhase2Config
        The active Phase-2 config; supplies ``registered_seeds``, ``split_seed``,
        ``oof_folds``, ``uncovered_tolerance``, ``method_roster`` and
        ``config_sha256``.
    response_artifact : Mapping
        ``{"response_space", "control_mean"}`` for the payload projection.
    fit_role_spec : FitRoleArtifactSpec
        The validated base fit-role artifact each fold subset is carved from.
    gene_order : sequence of str
        Canonical full transcriptome gene order.
    raw_data_sha256 : str
        Shared raw-data digest bound across artifact, projection and source.

    Returns
    -------
    SeedVariabilityReport
        The strict, self-checksummed development seed-variability report.

    Raises
    ------
    SeedVariabilityContractError
        On any whole-call contract/provenance violation (see the failure policy).
    FoldJobError
        On a fold-job leakage/contract violation (whole-call; not laundered).
    """
    # 1. store-type gate — reject anything but a typed DevelopmentOutcomeStore
    #    BEFORE any work (the sealed ComposeOutcomeStore, arrays, dicts, paths,
    #    arbitrary objects and injected payloads all fail here).
    if not isinstance(development_outcome_store, DevelopmentOutcomeStore):
        raise SeedVariabilityContractError(
            "development_outcome_store must be a DevelopmentOutcomeStore; got "
            f"{type(development_outcome_store).__name__}"
        )

    # 2. adapter roster gate — exactly {gears, cpa}, each a name-matched adapter.
    if set(baseline_adapters) != set(_SEED_LOOP_ROSTER):
        raise SeedVariabilityContractError(
            f"baseline_adapters must be exactly {sorted(_SEED_LOOP_ROSTER)}; "
            f"got {sorted(baseline_adapters)}"
        )
    for name, adapter in baseline_adapters.items():
        if not isinstance(adapter, BaselineAdapter) or adapter.name != name:
            raise SeedVariabilityContractError(f"invalid baseline adapter for {name!r}")

    # 3. config <-> manifest <-> inputs <-> store contract (whole-call on mismatch).
    _verify_orchestration_contract(
        config=config,
        oof_manifest=oof_manifest,
        inputs=inputs,
        development_outcome_store=development_outcome_store,
    )

    # 4. reconstruct the development delta truth ONCE (pair-aligned).
    delta_truth_by_pair = _build_delta_truth(inputs, development_outcome_store)

    fold_dir = _fold_artifact_dir(fit_role_spec)
    response_dim = int(inputs.response_dim)
    registered_seeds = tuple(int(s) for s in config.registered_seeds)
    n_folds = len(oof_manifest.folds)

    # the deterministic single-shot roster: config method roster minus the seed loop.
    deterministic_roster = tuple(m for m in config.method_roster if m not in _SEED_LOOP_ROSTER)

    status = SeedVariabilityStatus.COMPLETE
    summaries: list[SeedComparatorSummary] = []
    all_records: list[FoldExecutionRecord] = []
    all_fold_artifact_shas: list[str] = []
    worker_locks: set[str] = set()

    for method in sorted(baseline_adapters):
        adapter = baseline_adapters[method]
        oof_by_seed: dict[int, float] = {}
        failed_seeds: list[int] = []
        failure_class_by_seed: dict[int, str] = {}
        method_records: list[FoldExecutionRecord] = []

        for seed in registered_seeds:
            # Fold jobs are built OUTSIDE the per-seed try: a build_fold_job
            # leakage/contract failure (FoldJobError) is a whole-call failure, not
            # a stochastic per-seed execution failure, so it must not be laundered.
            fold_jobs: list[FoldJob] = []
            for fold_index in range(n_folds):
                job = build_fold_job(
                    method=method,
                    seed=seed,
                    fold_index=fold_index,
                    oof_manifest=oof_manifest,
                    inputs=inputs,
                    outcome_store=development_outcome_store,
                    response_artifact=response_artifact,
                    base_fit_role_spec=fit_role_spec,
                    fold_artifact_dir=fold_dir,
                    gene_order=gene_order,
                    raw_data_sha256=raw_data_sha256,
                )
                fold_jobs.append(job)
                all_fold_artifact_shas.append(job.fit_role_artifact_sha256)

            # Only the stochastic execution + reassembly is caught per-seed. We do
            # NOT catch BaseException; contract violations were validated up front
            # and cannot reach here, so any Exception here is a genuine execution
            # failure OF THIS SEED (record a scrubbed class, keep the seed).
            fold_results: list[FoldExecutionResult] = []
            try:
                for job in fold_jobs:
                    fold_results.append(
                        run_fold_job(
                            adapter,
                            job,
                            response_dim,
                            pair_manifest_checksum=inputs.manifest_checksum,
                            response_space_checksum=inputs.response_space_checksum,
                        )
                    )
                _predictions, scalar = assemble_seed_scalar(
                    fold_results,
                    manifest=oof_manifest,
                    delta_truth_by_pair=delta_truth_by_pair,
                    response_dim=response_dim,
                )
            except Exception as exc:  # noqa: BLE001 — see comment above (not BaseException)
                failed_seeds.append(int(seed))
                failure_class_by_seed[int(seed)] = type(exc).__name__  # scrubbed: class only
                status = SeedVariabilityStatus.INCOMPLETE
            else:
                if not math.isfinite(float(scalar)):
                    # a non-finite per-seed statistic marks the seed failed + INCOMPLETE.
                    failed_seeds.append(int(seed))
                    failure_class_by_seed[int(seed)] = "NonFiniteSeedScalar"
                    status = SeedVariabilityStatus.INCOMPLETE
                else:
                    oof_by_seed[int(seed)] = float(scalar)

            # Record every fold that executed (partial for a failed seed), binding
            # its real provenance digests + worker identity locks.
            for job, result in zip(fold_jobs, fold_results):
                record = _fold_record(method, seed, job, result)
                method_records.append(record)
                worker_locks.add(record.worker_identity_sha256)

        summary = _summarize_seed_scalars(
            method,
            registered_seeds,
            oof_by_seed=oof_by_seed,
            failed_seeds=failed_seeds,
            failure_class_by_seed=failure_class_by_seed,
            fold_records=method_records,
        )
        summaries.append(summary)
        all_records.extend(method_records)

    coverage = _build_coverage(oof_manifest, uncovered_tolerance=config.uncovered_tolerance)
    if coverage.uncovered_fraction > float(config.uncovered_tolerance):
        status = SeedVariabilityStatus.INCOMPLETE

    return SeedVariabilityReport(
        schema=_SEED_VARIABILITY_REPORT_SCHEMA,
        protocol=PROTOCOL,
        run_id=inputs.run_id,
        config_sha256=config.config_sha256,
        registered_seeds=registered_seeds,
        deterministic_roster=deterministic_roster,
        oof_manifest_checksum=oof_manifest.manifest_checksum,
        coverage=coverage,
        response_space_checksum=inputs.response_space_checksum,
        base_fit_role_artifact_sha256=fit_role_spec.sha256,
        fold_fit_role_artifact_sha256s=tuple(all_fold_artifact_shas),
        dev_store_content_checksum=development_outcome_store.content_checksum,
        worker_locks=tuple(sorted(worker_locks)),
        summaries=tuple(summaries),
        fold_execution_records=tuple(all_records),
        status=status,
    )
