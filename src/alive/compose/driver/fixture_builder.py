"""Committed COMPOSE fixture builder (sub-project C, spec §6).

Promotes the previously per-test synthetic-fixture assembly (``test_phase2a`` /
``test_phase2b`` / ``test_synthetic_gen`` ``_build_*`` helpers) into ONE committed
function, :func:`build_compose_fixture`, so the mini e2e drives the real
``phase2a → preflight → phase2b`` driver over a bounded synthetic corpus that
*faithfully mirrors the scientific stage-1 assembly* (spec §6).

The builder writes bounded synthetic **DATA only** — never a store object:

* a :class:`~alive.compose.phase2a.Phase2aInputs` payload (with the OOF selection
  parameters), serialized to disk AND carried in memory;
* a fit-role ``.h5ad``, a response artifact, a pair (split) manifest, a
  pair-index manifest, a ``source_kind='synthetic_fixture'`` non-sealed dev-store
  audit, and the sealed-outcome DATA (synthetic sealed source ``.h5ad`` +
  ``pair_index`` + manifest + ``approved_sealed_input_attestation`` + declared
  ``audit_path``);
* the per-method subprocess worker files (``worker_script`` = the committed
  ``scripts/baselines/stub_worker.py``; ``worker_config`` / ``resource_manifest``
  / ``requirements_lock`` / ``adapter_artifact`` written with the EXACT bytes the
  stub self-reports, so their file digests equal the stub constants);
* a fixture :class:`~alive.compose.driver.run_spec.ResolvedRunSpec` (``mode ==
  "fixture"``) pointing at all of the above with byte-matching declared digests
  and a recomputable ``run_id``.

It constructs **no** :class:`~alive.compose.phase2a.DevelopmentOutcomeStore` (built
by the ``phase2a`` subcommand from the dev-store DATA) and **no**
:class:`~alive.compose.outcome_store.ComposeOutcomeStore` (built by ``phase2b``
from the sealed-outcome DATA); it opens no seal and imports no ``gears`` / ``cpa``.
The run-produced artifacts (frozen bundle, OOF manifest, seed-variability report,
terminal, ledger, commit marker) are produced by *running the driver*, not here.

See docs/superpowers/specs/2026-07-07-compose-production-driver-design.md §6.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import anndata
import numpy as np
import pandas as pd
from scipy import sparse

from alive.compose.config2 import load_compose_phase2_config
from alive.compose.datacard import compute_compose_run_id
from alive.compose.driver.pair_index import (
    ATTESTATION_SCHEMA,
    PAIR_INDEX_MANIFEST_SCHEMA,
)
from alive.compose.driver.run_spec import (
    EXPECTED_HASHES_KEYS,
    PRE_SEAL_PATH_FIELDS,
    RESOLVED_RUN_SPEC_SCHEMA,
    RUN_PRODUCED_BASENAMES,
)
from alive.compose.fit_role import (
    FitRoleArtifactSpec,
    FitRoleExtraction,
    generate_fit_role_artifact,
)
from alive.compose.models import IDOnlyModel, L1Model, L2Model, L3Model
from alive.compose.operator import bilinear_predict
from alive.compose.outcome_store import FIXTURE_CORPUS_V1, FixtureCorpusAttestation
from alive.compose.phase2a import OutcomeAccessAudit, Phase2aInputs
from alive.compose.response import fit_response_space, verify_response_artifact
from alive.compose.split import ROLE_NAMES, build_split_manifest
from alive.provenance import sha256_file, sha256_json

__all__ = [
    "PROTOCOL",
    "PERTURBATION_COLUMN",
    "CONTROL_TOKEN",
    "COMBO_SEP",
    "STUB_WORKER_PATH",
    "FixtureBundle",
    "build_compose_fixture",
]

#: Active protocol the fixture spec declares.
PROTOCOL = "COMPOSE-K562-v1"

#: obs perturbation column / control token / combo separator used by the sealed
#: source and echoed in the pair-index manifest (must match the pre-seal schema
#: and the phase2b obs-alignment gate).
PERTURBATION_COLUMN = "perturbation"
CONTROL_TOKEN = "control"
COMBO_SEP = "_"

#: The committed reference subprocess worker (payload-v2), copied verbatim into
#: each fixture run so it is launchable and its self-hash matches the copy.
STUB_WORKER_PATH = Path(__file__).resolve().parents[4] / "scripts" / "baselines" / "stub_worker.py"

#: Committed config the fixture run identity binds ``config_digest`` to.
_CONFIG_PATH = "configs/compose_k562_v1_phase2.yaml"

#: The learned (non-baseline, non-adapter) model roster → a fresh-instance
#: factory each. GEARS/CPA are supplied as subprocess adapters, not factories.
_MODEL_CLASS_BY_NAME = {
    "l1_bilinear_identifiable": L1Model,
    "l2_saturation": L2Model,
    "l3_hypernetwork": L3Model,
    "id_only": IDOnlyModel,
}

#: Adapter methods dispatched to a subprocess worker (never a local factory).
_ADAPTER_METHODS = ("gears", "cpa")

#: Stub self-reported byte payloads (spec §5 / T4 reconcile). Each file the
#: builder writes with these EXACT bytes hashes to the stub's committed constant,
#: so the ``ExecutionIdentityLock`` assembler + worker-manifest verify pass.
_STUB_ADAPTER_BYTES = b"stub-response-operator-v2"
_STUB_CONFIG_BYTES = b"stub-config"
_STUB_RESOURCE_BYTES = b"stub-resource"
_STUB_ENVIRONMENT_BYTES = b"stub-environment"
_STUB_ADAPTER_VERSION = "stub-2"

#: Bounded synthetic-instance shape (kept within ``_assert_fixture_payload``).
_N_GENES = 18
_CALIBRATION_FRACTION = 12.0 / 18.0  # → 12 calibration genes (round-half-even)
_RESPONSE_DIM = 7
_ROWS_PER_PAIR = 2
_INSTANCE_SEED = 0
_NOISE = 0.02


# ---------------------------------------------------------------------------
# Returned bundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FixtureBundle:
    """Immutable handle to a built fixture corpus (paths + DATA, never a store).

    Attributes
    ----------
    run_id : str
        The fixed composite ``run_id`` bound identically into the
        ``Phase2aInputs`` and the fixture ResolvedRunSpec's four run-identity
        digests.
    spec_path : Path
        Path to the canonical fixture ResolvedRunSpec JSON.
    approved_artifacts_root : Path
        Canonical realpath trust root every declared path lives under.
    run_dir : Path
        The (empty) run directory the driver installs run-produced artifacts in.
    audit_path : Path
        The declared sealed-audit destination (``<run_dir>/audit.jsonl``); not
        created here (phase2b writes it).
    paths : Mapping[str, Path]
        Every written stage-1 file keyed by its pre-seal field name.
    worker_paths : Mapping[str, Path]
        The shared worker files keyed by role (``worker_script`` /
        ``worker_config`` / ``resource_manifest`` / ``requirements_lock`` /
        ``adapter_artifact``).
    expected_hashes : Mapping[str, str]
        The seven-key ``expected_hashes`` roster the spec declares (each equals
        the corresponding ``Phase2aInputs`` checksum).
    phase2a_inputs : Phase2aInputs
        The in-memory development inputs (identities/features only; NOT a store).
    dev_store_audit : Mapping[str, Any]
        The non-sealed dev-store DATA (calibration eps + pair ids + the
        ``source_kind='synthetic_fixture'`` access audit) a phase2a subcommand
        builds a :class:`DevelopmentOutcomeStore` FROM.
    sealed_outcome : Mapping[str, Any]
        The sealed-outcome DATA (pair_index, pair-index manifest, split manifest,
        attestation, sealed source path, audit_path, corpus attestation) a
        phase2b subcommand builds a :class:`ComposeOutcomeStore` FROM.
    fixture_corpus : FixtureCorpusAttestation
        The allowlisted synthetic-fixture corpus identity (``FIXTURE_CORPUS_V1``).
    response_artifact : Mapping[str, Any]
        The in-memory response artifact (``response_space`` + ``control_mean`` +
        ``combined_checksum``) and fit-role identity for the subprocess payload.
    """

    run_id: str
    spec_path: Path
    approved_artifacts_root: Path
    run_dir: Path
    audit_path: Path
    paths: Mapping[str, Path]
    worker_paths: Mapping[str, Path]
    expected_hashes: Mapping[str, str]
    phase2a_inputs: Phase2aInputs
    dev_store_audit: Mapping[str, Any]
    sealed_outcome: Mapping[str, Any]
    fixture_corpus: FixtureCorpusAttestation
    response_artifact: Mapping[str, Any]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _fixture_digest(label: str) -> str:
    """Deterministic 64-hex fixture digest derived in ONE place per label."""
    return hashlib.sha256(f"compose_c_fixture_v1::{label}".encode("utf-8")).hexdigest()


def _canonical_bytes(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _write_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _write_json(path: Path, obj: object) -> Path:
    return _write_bytes(path, _canonical_bytes(obj))


def _self_checksummed(body: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``body`` plus a ``self_checksum`` over the canonical body bytes."""
    payload = dict(body)
    payload["self_checksum"] = sha256_json(payload)
    return payload


def _path_sha(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": sha256_file(path)}


def _sym_to_vec(matrix: np.ndarray) -> np.ndarray:
    """Half-vectorise a symmetric matrix with the off-diagonal √2 weighting."""
    k = matrix.shape[0]
    iu = np.triu_indices(k)
    out = matrix[iu].astype(np.float64).copy()
    off = iu[0] != iu[1]
    out[off] *= np.sqrt(2.0)
    return out


# ---------------------------------------------------------------------------
# Synthetic assembly (promoted from the per-test _build_* helpers)
# ---------------------------------------------------------------------------


def _build_instance(manifest: Mapping[str, Any], *, k_grid: tuple[int, ...]) -> dict[str, Any]:
    """A full-rank bilinear synthetic instance aligned to the split roles.

    The calibration design (development role) is the manifest's
    ``combo_calibration`` pairs; the sealed pair identities are its
    ``sealed_double_unseen`` / ``sealed_single_unseen`` pairs — so the frozen
    bundle a phase2a run produces covers EXACTLY the manifest's sealed roles
    (preflight parity) and the calibration outcomes align with the dev store.
    """
    roles = manifest["roles"]
    cal_pairs = [tuple(p) for p in roles["combo_calibration"]]
    sealed_double = [tuple(p) for p in roles["sealed_double_unseen"]]
    sealed_single = [tuple(p) for p in roles["sealed_single_unseen"]]
    gene_ids = sorted(
        {g for role in ROLE_NAMES for pair in roles[role] for g in pair},
        key=lambda s: s.encode("utf-8"),
    )
    gene_index = {g: i for i, g in enumerate(gene_ids)}
    n_genes = len(gene_ids)
    p = _RESPONSE_DIM
    k0 = int(k_grid[0])

    rng = np.random.default_rng(_INSTANCE_SEED)
    z0 = rng.normal(size=(n_genes, k0))
    coef = np.vstack(
        [_sym_to_vec(0.5 * (b + b.T)) for b in (rng.normal(size=(k0, k0)) for _ in range(p))]
    )

    cal_idx = [(gene_index[a], gene_index[b]) for a, b in cal_pairs]
    eps_cal = np.vstack([bilinear_predict(coef, z0[gi], z0[hi]) for gi, hi in cal_idx])
    additive_cal = rng.normal(size=eps_cal.shape)
    eps_a = eps_cal + _NOISE * rng.normal(size=eps_cal.shape)
    eps_b = eps_cal + _NOISE * rng.normal(size=eps_cal.shape)
    delta_by_gene = {g: rng.normal(size=p) for g in gene_ids}

    factors_by_k: dict[int, np.ndarray] = {}
    for k_total in k_grid:
        kt = int(k_total)
        if kt == k0:
            factors_by_k[kt] = z0
        else:
            extra = [z0[:, i % k0] ** 2 for i in range(kt - k0)]
            factors_by_k[kt] = np.column_stack([z0, *extra])

    return {
        "gene_ids": gene_ids,
        "gene_index": gene_index,
        "n_genes": n_genes,
        "p": p,
        "factors_by_k": factors_by_k,
        "cal_pairs": cal_pairs,
        "cal_idx": cal_idx,
        "eps_cal": eps_cal,
        "additive_cal": additive_cal,
        "eps_a": eps_a,
        "eps_b": eps_b,
        "sealed_double": sealed_double,
        "sealed_single": sealed_single,
        "delta_by_gene": delta_by_gene,
    }


def _build_response_and_fit_role(
    *,
    out_path: Path,
    response_dim: int,
    raw_data_sha256: str,
    cal_pair_ids: list[tuple[str, str]],
) -> tuple[dict[str, Any], list[str], FitRoleArtifactSpec, str]:
    """A real response space + written fit-role ``.h5ad`` (promoted helper)."""
    rng = np.random.default_rng(4242)
    n_genes = response_dim + 1
    gene_order = [f"T{i}" for i in range(n_genes)]
    combo_pairs = cal_pair_ids[: min(4, len(cal_pair_ids))]
    n_control, n_single, n_combo = 12, 8, len(combo_pairs)
    n_cells = n_control + n_single + n_combo
    counts = rng.integers(1, 50, size=(n_cells, n_genes)).astype(np.float64)
    X = sparse.csr_matrix(counts)
    control_idx = np.arange(0, n_control)
    single_idx = np.arange(n_control, n_control + n_single)
    space = fit_response_space(
        X,
        control_idx=control_idx,
        eligible_single_idx=single_idx,
        n_hvg=n_genes,
        pca_dim=response_dim,
        seed=0,
    )
    control_mean = space.project(X, control_idx).mean(axis=0)
    _, _, combined = verify_response_artifact(space, control_mean)

    combo_genes = [g for pair in combo_pairs for g in pair]
    rows = (
        [(f"c{i}", "control", "control") for i in range(n_control)]
        + [(f"s{i}", "singles", combo_genes[i % len(combo_genes)]) for i in range(n_single)]
        + [
            (f"m{i}", "combo_calibration", f"{a}{COMBO_SEP}{b}")
            for i, (a, b) in enumerate(combo_pairs)
        ]
    )
    extraction = FitRoleExtraction(
        X=X,
        var_names=tuple(gene_order),
        rows=tuple(rows),
        role_counts={"control": n_control, "singles": n_single, "combo_calibration": n_combo},
        raw_data_sha256=raw_data_sha256,
        pair_manifest_sha256=_fixture_digest("fit_role_pair_manifest"),
        eligibility_hash=_fixture_digest("fit_role_eligibility"),
    )
    spec = generate_fit_role_artifact(
        extraction=extraction,
        out_path=str(out_path),
        config_sha256=_fixture_digest("fit_role_config"),
        data_card_sha256=_fixture_digest("fit_role_data_card"),
        calibration_gene_set_hash=_fixture_digest("fit_role_cal_gene_set"),
        generator_code_sha256=_fixture_digest("fit_role_generator"),
        writer_environment_sha256=_fixture_digest("fit_role_writer_env"),
    )
    response_artifact = {"response_space": space, "control_mean": control_mean}
    return response_artifact, gene_order, spec, combined


def _build_sealed_source(
    manifest: Mapping[str, Any], *, out_path: Path, n_source_genes: int
) -> tuple[dict[tuple[str, str], np.ndarray], list[tuple[str, str, str]], str]:
    """Write the synthetic sealed source ``.h5ad``; return the pair-index DATA.

    Each canonical pair (all three roles) is assigned a disjoint block of source
    rows whose obs perturbation label canonicalizes to that pair — so the phase2b
    obs-alignment gate (``validate_pair_index_against_source_obs``) accepts it.
    """
    rng = np.random.default_rng(1234)
    roles = manifest["roles"]
    ordered: list[tuple[tuple[str, str], str]] = []
    for role in ROLE_NAMES:
        for pair in roles[role]:
            ordered.append(((pair[0], pair[1]), role))

    pair_index: dict[tuple[str, str], np.ndarray] = {}
    entries: list[tuple[str, str, str]] = []  # (pair, role) row-block descriptors
    obs_labels: list[str] = []
    obs_roles: list[str] = []
    cursor = 0
    for (a, b), role in ordered:
        rows = np.arange(cursor, cursor + _ROWS_PER_PAIR, dtype=np.int64)
        pair_index[(a, b)] = rows
        obs_labels.extend([f"{a}{COMBO_SEP}{b}"] * _ROWS_PER_PAIR)
        obs_roles.extend([role] * _ROWS_PER_PAIR)
        entries.append((a, b, role))
        cursor += _ROWS_PER_PAIR

    counts = rng.integers(1, 50, size=(cursor, n_source_genes)).astype(np.float64)
    counts[:, 0] += 1.0  # every cell a positive library size
    obs = pd.DataFrame(
        {PERTURBATION_COLUMN: obs_labels, "role": obs_roles},
        index=[f"cell{i}" for i in range(cursor)],
    )
    adata = anndata.AnnData(X=sparse.csr_matrix(counts), obs=obs)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    adata.write_h5ad(out_path)
    obs_row_identity = sha256_json(obs_labels)
    return pair_index, entries, obs_row_identity


def _build_phase2a_inputs(
    instance: Mapping[str, Any],
    *,
    config,
    run_id: str,
    checksums: Mapping[str, str],
) -> Phase2aInputs:
    """Assemble the in-memory ``Phase2aInputs`` (identities/features only)."""
    model_factories = {
        name: _MODEL_CLASS_BY_NAME[name]
        for name in config.method_roster
        if name in _MODEL_CLASS_BY_NAME
    }
    return Phase2aInputs(
        run_id=run_id,
        gene_index=instance["gene_index"],
        factors_by_k=instance["factors_by_k"],
        cal_idx_pairs=instance["cal_idx"],
        cal_pair_ids=instance["cal_pairs"],
        additive_cal=instance["additive_cal"],
        eps_split_a=instance["eps_a"],
        eps_split_b=instance["eps_b"],
        k_total_grid=list(config.total_k_grid),
        lambda_grid=list(config.lambda_grid),
        n_genes=instance["n_genes"],
        n_folds=config.oof_folds,
        seed=config.split_seed,
        uncovered_tolerance=config.uncovered_tolerance,
        sealed_double_pair_ids=instance["sealed_double"],
        sealed_single_pair_ids=instance["sealed_single"],
        delta_by_gene=instance["delta_by_gene"],
        model_factories=model_factories,
        response_dim=instance["p"],
        response_space_checksum=checksums["response_space_checksum"],
        factor_checksum=checksums["factor_checksum"],
        manifest_checksum=checksums["manifest_checksum"],
        environment_checksum=checksums["environment_checksum"],
        registered_seeds=config.registered_seeds,
        data_card_checksum=checksums["data_card_checksum"],
        raw_data_checksum=checksums["raw_data_checksum"],
        sequence_mapping_checksum=checksums["sequence_mapping_checksum"],
    )


def _serialize_phase2a_inputs(inputs: Phase2aInputs) -> dict[str, Any]:
    """A deterministic, JSON-serialisable view of the development inputs.

    Callables (``model_factories``) are serialised as their ordered roster names;
    a phase2a subcommand reconstructs the factories from the registered roster.
    """
    return {
        "schema": "compose_phase2a_inputs_fixture_v1",
        "run_id": inputs.run_id,
        "gene_index": {g: int(i) for g, i in inputs.gene_index.items()},
        "factors_by_k": {
            str(k): np.asarray(inputs.factors_by_k[k]).tolist() for k in sorted(inputs.factors_by_k)
        },
        "cal_idx_pairs": [list(p) for p in inputs.cal_idx_pairs],
        "cal_pair_ids": [list(p) for p in inputs.cal_pair_ids],
        "additive_cal": np.asarray(inputs.additive_cal).tolist(),
        "eps_split_a": np.asarray(inputs.eps_split_a).tolist(),
        "eps_split_b": np.asarray(inputs.eps_split_b).tolist(),
        "k_total_grid": [int(x) for x in inputs.k_total_grid],
        "lambda_grid": [float(x) for x in inputs.lambda_grid],
        "n_genes": int(inputs.n_genes),
        "n_folds": int(inputs.n_folds),
        "seed": int(inputs.seed),
        "uncovered_tolerance": float(inputs.uncovered_tolerance),
        "sealed_double_pair_ids": [list(p) for p in inputs.sealed_double_pair_ids],
        "sealed_single_pair_ids": [list(p) for p in inputs.sealed_single_pair_ids],
        "delta_by_gene": {
            g: np.asarray(inputs.delta_by_gene[g]).tolist() for g in inputs.delta_by_gene
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
        "content_checksum": inputs.content_checksum,
    }


def _worker_block(worker_paths: Mapping[str, Path], *, representation: str) -> dict[str, Any]:
    """One per-method subprocess worker block (spec §2.2 / §5)."""
    return {
        "env_python": sys.executable,
        "worker_script": _path_sha(worker_paths["worker_script"]),
        "import_name": "json",
        "worker_config": _path_sha(worker_paths["worker_config"]),
        "resource_manifest": _path_sha(worker_paths["resource_manifest"]),
        "requirements_lock": _path_sha(worker_paths["requirements_lock"]),
        "adapter_artifact": _path_sha(worker_paths["adapter_artifact"]),
        "execution_identity_lock": {
            "prediction_representation": representation,
            "environment_lock_sha256": hashlib.sha256(_STUB_ENVIRONMENT_BYTES).hexdigest(),
            "adapter_version": _STUB_ADAPTER_VERSION,
            "adapter_sha256": hashlib.sha256(_STUB_ADAPTER_BYTES).hexdigest(),
            "config_sha256": hashlib.sha256(_STUB_CONFIG_BYTES).hexdigest(),
            "resource_sha256": hashlib.sha256(_STUB_RESOURCE_BYTES).hexdigest(),
        },
    }


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


def build_compose_fixture(tmp_root: Path) -> FixtureBundle:
    """Build the committed synthetic stage-1 corpus + fixture ResolvedRunSpec.

    Writes bounded synthetic DATA under ``realpath(tmp_root)`` and a canonical
    fixture ResolvedRunSpec pointing at it. Every declared pre-seal path exists
    with a byte-matching ``sha256``; each worker block declares an
    ``adapter_artifact`` plus the four other path+SHA fields; the ``run_id``
    recomputes from the four run-identity digests and equals
    ``Phase2aInputs.run_id``; the pair-index manifest binds to its attestation;
    the sealed-outcome corpus identity is ``FIXTURE_CORPUS_V1``. Constructs NO
    store object, opens no seal.

    Parameters
    ----------
    tmp_root : Path
        A writable directory to serve as the approved-artifacts trust root.

    Returns
    -------
    FixtureBundle
        Paths + spec path + the fixed ``run_id`` + the in-memory development /
        sealed-outcome DATA (never a store).
    """
    root = Path(os.path.realpath(str(tmp_root)))
    stage1 = root / "stage1"
    workers_dir = root / "workers"
    run_dir = root / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    stage1.mkdir(parents=True, exist_ok=True)
    audit_path = run_dir / "audit.jsonl"

    config = load_compose_phase2_config(_CONFIG_PATH)

    # --- 1. split (pair) manifest + aligned synthetic instance ----------------
    gene_ids = [f"G{i:02d}" for i in range(_N_GENES)]
    eligible_pairs = [
        (gene_ids[i], gene_ids[j]) for i in range(_N_GENES) for j in range(i + 1, _N_GENES)
    ]
    manifest = build_split_manifest(
        eligible_pairs, seed=config.split_seed, calibration_fraction=_CALIBRATION_FRACTION
    )
    for role in ROLE_NAMES:
        if not manifest["roles"][role]:
            raise ValueError(
                f"synthetic split produced an empty {role!r} role; adjust the "
                "calibration fraction / gene universe"
            )
    instance = _build_instance(manifest, k_grid=config.total_k_grid)

    # --- 2. response artifact + fit-role .h5ad --------------------------------
    fit_role_raw_sha = _fixture_digest("fit_role_raw_data")
    response_artifact, gene_order, fit_role_spec, response_combined = _build_response_and_fit_role(
        out_path=stage1 / "fit_role.h5ad",
        response_dim=instance["p"],
        raw_data_sha256=fit_role_raw_sha,
        cal_pair_ids=instance["cal_pairs"],
    )

    # --- 3. fixed run identity + expected-hashes roster -----------------------
    data_card_digest = _fixture_digest("data_card")
    raw_or_source_digest = _fixture_digest("raw_or_source")
    sequence_mapping_digest = _fixture_digest("sequence_mapping")
    run_id = compute_compose_run_id(
        config_digest=config.config_sha256,
        data_card_digest=data_card_digest,
        raw_or_source_digest=raw_or_source_digest,
        sequence_mapping_digest=sequence_mapping_digest,
    )
    checksums = {
        "response_space_checksum": response_combined,
        "factor_checksum": _fixture_digest("factor_bank"),
        "manifest_checksum": manifest["checksum"],
        "environment_checksum": _fixture_digest("environment"),
        "data_card_checksum": data_card_digest,
        "raw_data_checksum": raw_or_source_digest,
        "sequence_mapping_checksum": sequence_mapping_digest,
    }
    assert set(checksums) == set(EXPECTED_HASHES_KEYS)

    # --- 4. Phase2aInputs (in memory) + serialized payload --------------------
    phase2a_inputs = _build_phase2a_inputs(
        instance, config=config, run_id=run_id, checksums=checksums
    )

    # --- 5. non-sealed dev-store DATA (source_kind='synthetic_fixture') -------
    dev_source_obj = {
        "schema": "compose_development_outcome_source_v1",
        "combo_calibration_pair_ids": [list(p) for p in instance["cal_pairs"]],
        "combo_calibration_eps": np.asarray(instance["eps_cal"]).tolist(),
        "source_kind": "synthetic_fixture",
    }
    dev_source_path = _write_json(stage1 / "development_outcome_source.json", dev_source_obj)
    dev_source_sha = sha256_file(dev_source_path)
    access_audit = {
        "role": "combo_calibration",
        "manifest_checksum": manifest["checksum"],
        "source_checksum": dev_source_sha,
        "sealed_access_count": 0,
        "source_kind": "synthetic_fixture",
    }
    dev_manifest_path = _write_json(
        stage1 / "development_outcome_manifest.json",
        {"schema": "compose_development_outcome_manifest_v1", "access_audit": access_audit},
    )
    # An OutcomeAccessAudit-shaped object is DATA, not a store; carry it so a
    # phase2a subcommand can construct the DevelopmentOutcomeStore from it.
    dev_store_audit = {
        "combo_calibration_eps": np.asarray(instance["eps_cal"]),
        "combo_calibration_pair_ids": tuple(instance["cal_pairs"]),
        "access_audit": OutcomeAccessAudit(**access_audit),
    }

    # --- 6. sealed-outcome DATA (source + pair_index + manifest + audit) ------
    sealed_source_path = stage1 / "sealed_source.h5ad"
    pair_index, pair_entries, obs_row_identity = _build_sealed_source(
        manifest, out_path=sealed_source_path, n_source_genes=instance["p"] + 1
    )
    sealed_source_sha = sha256_file(sealed_source_path)

    pair_index_body = {
        "schema": PAIR_INDEX_MANIFEST_SCHEMA,
        "source_file_sha256": sealed_source_sha,
        "obs_row_identity_sha256": obs_row_identity,
        "perturbation_column": PERTURBATION_COLUMN,
        "control_token": CONTROL_TOKEN,
        "combo_sep": COMBO_SEP,
        "pairs": [
            {
                "gene_a": a,
                "gene_b": b,
                "role": role,
                "row_indices": [int(i) for i in pair_index[(a, b)]],
                "row_id_sha256": sha256_json(
                    {"pair": [a, b], "rows": [int(i) for i in pair_index[(a, b)]]}
                ),
            }
            for (a, b, role) in pair_entries
        ],
    }
    pair_index_manifest = _self_checksummed(pair_index_body)
    pair_index_manifest_path = _write_json(stage1 / "pair_index_manifest.json", pair_index_manifest)

    attestation_body = {
        "schema": ATTESTATION_SCHEMA,
        "canonical_source_path": str(sealed_source_path),
        "expected_source_file_sha256": sealed_source_sha,
        "snapshot_id": "compose_c_fixture_v1_snapshot",
        "source_row_identity_sha256": obs_row_identity,
        "pair_index_file_sha256": sha256_file(pair_index_manifest_path),
    }
    attestation = _self_checksummed(attestation_body)
    attestation_path = _write_json(stage1 / "approved_sealed_input_attestation.json", attestation)

    # --- 7. remaining opaque-to-loader stage-1 DATA files ---------------------
    pair_manifest_path = _write_json(stage1 / "pair_manifest.json", manifest)
    phase2a_inputs_path = _write_json(
        stage1 / "phase2a_inputs.json", _serialize_phase2a_inputs(phase2a_inputs)
    )
    response_artifact_path = _write_json(
        stage1 / "response_artifact.json",
        {
            "schema": "compose_response_artifact_fixture_v1",
            "response_space": json.loads(response_artifact["response_space"].artifact_bytes()),
            "control_mean": np.asarray(response_artifact["control_mean"]).tolist(),
            "combined_checksum": response_combined,
            "gene_order": list(gene_order),
            "raw_data_sha256": fit_role_raw_sha,
            "fit_role_artifact": fit_role_spec.to_payload_block(),
        },
    )
    config_bytes = Path(_CONFIG_PATH).read_bytes()
    config_path = _write_bytes(stage1 / "config.yaml", config_bytes)
    data_card_path = _write_json(
        stage1 / "data_card.json",
        {
            "schema": "compose_data_card_fixture_v1",
            "raw_or_source": {"kind": "declared_source_digest", "digest": raw_or_source_digest},
            "data_card_digest": data_card_digest,
        },
    )
    raw_asset_path = _write_bytes(
        stage1 / "raw_asset.bin", b"compose_c_fixture_v1::synthetic-raw-asset"
    )
    sequence_mapping_path = _write_json(
        stage1 / "sequence_mapping.json",
        {"schema": "compose_sequence_mapping_fixture_v1", "digest": sequence_mapping_digest},
    )
    feature_bank_path = _write_json(
        stage1 / "feature_bank.json", {"schema": "compose_feature_bank_fixture_v1"}
    )
    factor_bank_path = _write_json(
        stage1 / "factor_bank.json",
        {
            "schema": "compose_factor_bank_fixture_v1",
            "factor_checksum": checksums["factor_checksum"],
            "k_grid": [int(k) for k in config.total_k_grid],
        },
    )

    pre_seal_paths = {
        "config": config_path,
        "data_card": data_card_path,
        "raw_asset": raw_asset_path,
        "sequence_mapping": sequence_mapping_path,
        "feature_bank": feature_bank_path,
        "factor_bank": factor_bank_path,
        "response_artifact": response_artifact_path,
        "fit_role_artifact": stage1 / "fit_role.h5ad",
        "phase2a_inputs": phase2a_inputs_path,
        "development_outcome_source": dev_source_path,
        "development_outcome_manifest": dev_manifest_path,
        "pair_manifest": pair_manifest_path,
        "pair_index_manifest": pair_index_manifest_path,
        "approved_sealed_input_attestation": attestation_path,
    }
    assert set(pre_seal_paths) == set(PRE_SEAL_PATH_FIELDS)

    # --- 8. worker files (stub bytes) -----------------------------------------
    worker_paths = {
        "worker_script": _write_bytes(
            workers_dir / "stub_worker.py", STUB_WORKER_PATH.read_bytes()
        ),
        "worker_config": _write_bytes(workers_dir / "worker_config.json", _STUB_CONFIG_BYTES),
        "resource_manifest": _write_bytes(
            workers_dir / "resource_manifest.json", _STUB_RESOURCE_BYTES
        ),
        "requirements_lock": _write_bytes(
            workers_dir / "requirements.lock", _STUB_ENVIRONMENT_BYTES
        ),
        "adapter_artifact": _write_bytes(workers_dir / "adapter.bin", _STUB_ADAPTER_BYTES),
    }
    representations = {name: rep for name, rep, _bias in config.baseline_representations}
    worker_blocks = {
        method: _worker_block(worker_paths, representation=representations[method])
        for method in _ADAPTER_METHODS
    }

    # --- 9. assemble + self-checksum + write the fixture ResolvedRunSpec ------
    spec_body: dict[str, Any] = {
        "schema": RESOLVED_RUN_SPEC_SCHEMA,
        "mode": "fixture",
        "protocol": PROTOCOL,
        "run_id": run_id,
        "approved_git_sha": "0" * 40,
        "run_dir": str(run_dir),
        "approved_artifacts_root": str(root),
        "config_digest": config.config_sha256,
        "data_card_digest": data_card_digest,
        "raw_or_source_digest": raw_or_source_digest,
        "sequence_mapping_digest": sequence_mapping_digest,
        "run_produced_basenames": dict(RUN_PRODUCED_BASENAMES),
        "expected_hashes": dict(checksums),
        "worker_blocks": worker_blocks,
        "fixture": {
            "fixture_corpus_id": FIXTURE_CORPUS_V1.corpus_id,
            "builder_code_digest": FIXTURE_CORPUS_V1.builder_code_sha256,
            "sealed_input": {
                "source_path": str(sealed_source_path),
                "expected_file_sha256": sealed_source_sha,
                "audit_path": str(audit_path),
            },
        },
    }
    for field in PRE_SEAL_PATH_FIELDS:
        spec_body[field] = _path_sha(pre_seal_paths[field])
    spec = _self_checksummed(spec_body)
    spec_path = _write_bytes(root / "resolved_run_spec.json", _canonical_bytes(spec))

    sealed_outcome = {
        "source_path": sealed_source_path,
        "source_file_sha256": sealed_source_sha,
        "pair_index": pair_index,
        "pair_index_manifest": pair_index_manifest,
        "manifest": manifest,
        "attestation": attestation,
        "audit_path": audit_path,
        "perturbation_column": PERTURBATION_COLUMN,
        "combo_sep": COMBO_SEP,
        "corpus_id": FIXTURE_CORPUS_V1.corpus_id,
        "source_sha256": FIXTURE_CORPUS_V1.source_sha256,
        "builder_code_sha256": FIXTURE_CORPUS_V1.builder_code_sha256,
    }
    response_bundle = {
        "response_space": response_artifact["response_space"],
        "control_mean": response_artifact["control_mean"],
        "combined_checksum": response_combined,
        "gene_order": gene_order,
        "fit_role_spec": fit_role_spec,
        "raw_data_sha256": fit_role_raw_sha,
    }

    return FixtureBundle(
        run_id=run_id,
        spec_path=spec_path,
        approved_artifacts_root=root,
        run_dir=run_dir,
        audit_path=audit_path,
        paths=MappingProxyType(dict(pre_seal_paths)),
        worker_paths=MappingProxyType(dict(worker_paths)),
        expected_hashes=MappingProxyType(dict(checksums)),
        phase2a_inputs=phase2a_inputs,
        dev_store_audit=MappingProxyType(dev_store_audit),
        sealed_outcome=MappingProxyType(sealed_outcome),
        fixture_corpus=FIXTURE_CORPUS_V1,
        response_artifact=MappingProxyType(response_bundle),
    )
