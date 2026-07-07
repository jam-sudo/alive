"""Controller-side fold jobs for COMPOSE development seed-variability (D2 Task 3).

SYNTHETIC-SAFE: pure ``numpy`` + a re-derived fit-role artifact. This module builds,
for ONE gene-disjoint OOF calibration fold, a fold-scoped fit job whose worker payload
trains ONLY on that fold's TRAIN combo pairs. The fold's held-out TEST pairs and its
cross-group EXCLUDED pairs are fully absent from both the fold-scoped fit-role artifact
and the payload — this is the leakage-critical heart of D2's per-seed OOF error
measurement.

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
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from alive.compose.baseline_subprocess import _REQUIRED_KEYS
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
    build_subprocess_fit_payload,
)
from alive.compose.select import OOFFoldManifest

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
