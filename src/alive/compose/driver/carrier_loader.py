"""From-disk stage-1 carrier loader (COMPOSE production driver, Task 11.5).

The four driver subcommands (Tasks 7-10) consume a fuller in-memory DATA carrier
than a bare :class:`~alive.compose.driver.run_spec.ResolvedRunSpec`: they read
``spec_path`` PLUS the live stage-1 objects the committed fixture builder's
:class:`~alive.compose.driver.fixture_builder.FixtureBundle` carries
(``phase2a_inputs`` / ``dev_store_audit`` / ``response_artifact`` /
``sealed_outcome``). The only committed carrier SOURCE is
:func:`~alive.compose.driver.fixture_builder.build_compose_fixture`, a write-once
one-time producer — so a CLI that rebuilds the carrier per process can run at most
ONE subcommand per approved-root, making the spec §0/§1.1/§11 THREE-INDEPENDENT-
PROCESS ``phase2a → preflight → phase2b`` e2e impossible.

This module closes that gap. :func:`load_run_spec_carrier` reconstructs the carrier
purely from the ResolvedRunSpec's ALREADY-serialized, SHA-verified on-disk stage-1
artifacts — it is a LOADER, not a producer: it writes NO new bytes, changes NO
serialization, and constructs NO
:class:`~alive.compose.outcome_store.ComposeOutcomeStore` (the seal boundary is
``phase2b``'s alone, spec §4). Every consumed field is already declared in
:data:`~alive.compose.driver.run_spec.PRE_SEAL_PATH_FIELDS` and byte-SHA-verified
by :func:`~alive.compose.driver.run_spec.load_resolved_run_spec`, so each process
reconstructs a byte-faithful carrier from disk.

Fidelity (seal-critical). The response-space payload is serialized ROUNDED (via
:meth:`~alive.compose.response.ResponseSpace.artifact_bytes`), so recomputing the
space checksum from the rounded payload reproduces the built space's checksum
(rounding is idempotent); the COMBINED (space + control_mean) digest the phase2a
hash gate compares against therefore rehydrates exactly (see
``phase2a.py`` ``build_subprocess_fit_payload`` gate).

Scientific mode has no committed carrier path yet (raw Norman -> ``Phase2aInputs`` /
factor bank / response artifact / pair manifest is a separate PREPARE obligation,
spec §0 "Out of scope"): a scientific ResolvedRunSpec fails closed here with
:class:`UnsupportedModeError` rather than being dispatched against a carrier this
loader cannot yet build.

See docs/superpowers/specs/2026-07-07-compose-production-driver-design.md §0/§1.1/§11.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from alive.compose.config2 import ActivationRecord
from alive.compose.driver.fixture_builder import _MODEL_CLASS_BY_NAME
from alive.compose.driver.run_spec import (
    ResolvedRunSpec,
    RunSpecError,
    load_resolved_run_spec,
)
from alive.compose.fit_role import FitRoleArtifactSpec
from alive.compose.outcome_store import FIXTURE_CORPUS_V1
from alive.compose.phase2a import OutcomeAccessAudit, Phase2aInputs
from alive.compose.phase2b import ActivationProvenanceInputs
from alive.compose.response import ResponseSpace
from alive.provenance import EnvironmentInfo, sha256_bytes

__all__ = [
    "RunSpecCarrier",
    "UnsupportedModeError",
    "load_run_spec_carrier",
]

_MODES = frozenset({"fixture", "scientific"})


class UnsupportedModeError(RunSpecError):
    """Raised when this loader cannot yet construct a carrier for the spec's mode.

    Subclasses :class:`~alive.compose.driver.run_spec.RunSpecError` so it is caught
    by the CLI's SAME known-pre-seal-rejection mapping (exit ``10``) without a
    separate ``except`` clause. Scientific-mode carrier assembly is a separate
    PREPARE sub-project obligation (spec §0 "Out of scope"); a scientific
    ResolvedRunSpec fails closed here rather than being dispatched against a
    carrier this loader has no way to build.
    """


@dataclass(frozen=True)
class RunSpecCarrier:
    """The from-disk-reconstructed stage-1 DATA carrier (a ``FixtureBundle`` peer).

    Exposes exactly the attributes the three carrier-consuming subcommands
    (``phase2a`` / ``preflight`` / ``phase2b``) read — duck-compatible with the
    committed :class:`~alive.compose.driver.fixture_builder.FixtureBundle` for that
    consumed surface. It carries NO store object and opens NO seal.

    Attributes
    ----------
    spec_path : pathlib.Path
        Path to the canonical ResolvedRunSpec JSON the carrier was loaded from.
    phase2a_inputs : alive.compose.phase2a.Phase2aInputs
        The rehydrated development inputs (identities/features only; NOT a store).
    dev_store_audit : Mapping
        The non-sealed dev-store DATA (``combo_calibration_eps`` /
        ``combo_calibration_pair_ids`` / ``access_audit``) a ``phase2a`` subcommand
        builds a :class:`~alive.compose.phase2a.DevelopmentOutcomeStore` FROM.
    response_artifact : Mapping
        The live response artifact (``response_space`` / ``control_mean`` /
        ``combined_checksum`` / ``gene_order`` / ``raw_data_sha256`` /
        ``fit_role_spec``) for the subprocess payload + preflight cross-check.
    sealed_outcome : Mapping
        The sealed-outcome DATA (``manifest`` / ``pair_index`` /
        ``pair_index_manifest`` / ``source_path`` / ``source_file_sha256`` /
        ``perturbation_column`` / ``combo_sep`` + the corpus attestation triple)
        a ``phase2b`` subcommand builds its sealed store FROM. No outcome bytes are
        read here (``phase2b`` opens the source ``O_NOFOLLOW`` at seal time).
    mode : str
        The discriminant: ``"fixture"`` or ``"scientific"``. Determines whether
        the six scientific fields below must be all ``None`` or all populated
        (``__post_init__`` enforces this exactly; see §3).
    activation_record : alive.compose.config2.ActivationRecord or None
        Owner authorization for scientific mode; ``None`` in fixture mode.
    git_is_clean : bool or None
        Must be exactly ``True`` in scientific mode; ``None`` in fixture mode.
    environment : alive.provenance.EnvironmentInfo or None
        Captured runtime environment snapshot for scientific mode; ``None`` in
        fixture mode.
    data_card_path : pathlib.Path or None
        Path to the scientific run's data card; ``None`` in fixture mode.
    raw_asset_path : pathlib.Path or None
        Path to the scientific run's raw asset; ``None`` in fixture mode.
    provenance_inputs : alive.compose.phase2b.ActivationProvenanceInputs or None
        Evidence-sourced provenance digests for scientific mode; ``None`` in
        fixture mode.
    """

    spec_path: Path
    phase2a_inputs: Phase2aInputs
    dev_store_audit: Mapping[str, Any]
    response_artifact: Mapping[str, Any]
    sealed_outcome: Mapping[str, Any]
    mode: str = "fixture"
    activation_record: ActivationRecord | None = None
    git_is_clean: bool | None = None
    environment: EnvironmentInfo | None = None
    data_card_path: Path | None = None
    raw_asset_path: Path | None = None
    provenance_inputs: ActivationProvenanceInputs | None = None

    _SCIENTIFIC_FIELDS = (
        "activation_record",
        "git_is_clean",
        "environment",
        "data_card_path",
        "raw_asset_path",
        "provenance_inputs",
    )

    def __post_init__(self) -> None:
        """Enforce exact population by ``mode``: all-None fixture, all-typed scientific (§3)."""
        if self.mode == "fixture":
            populated = [f for f in self._SCIENTIFIC_FIELDS if getattr(self, f) is not None]
            if populated:
                raise ValueError(
                    f"fixture carrier must leave every scientific field None; got {populated}"
                )
            return
        if self.mode == "scientific":
            missing = [f for f in self._SCIENTIFIC_FIELDS if getattr(self, f) is None]
            if missing:
                raise ValueError(
                    f"scientific carrier requires every scientific field; missing {missing}"
                )
            if not isinstance(self.activation_record, ActivationRecord):
                raise ValueError("scientific activation_record must be an ActivationRecord")
            if self.git_is_clean is not True:
                raise ValueError("scientific git_is_clean must be exactly True")
            if not isinstance(self.environment, EnvironmentInfo):
                raise ValueError("scientific environment must be an EnvironmentInfo")
            if not isinstance(self.provenance_inputs, ActivationProvenanceInputs):
                raise ValueError("scientific provenance_inputs must be ActivationProvenanceInputs")
            if not isinstance(self.data_card_path, Path) or not isinstance(
                self.raw_asset_path, Path
            ):
                raise ValueError("scientific data_card_path / raw_asset_path must be Path")
            return
        raise ValueError(
            f"RunSpecCarrier.mode must be 'fixture' or 'scientific', got {self.mode!r}"
        )

    @classmethod
    def _fixture(
        cls, *, spec_path, phase2a_inputs, dev_store_audit, response_artifact, sealed_outcome
    ) -> "RunSpecCarrier":
        return cls(
            spec_path=spec_path,
            phase2a_inputs=phase2a_inputs,
            dev_store_audit=dev_store_audit,
            response_artifact=response_artifact,
            sealed_outcome=sealed_outcome,
            mode="fixture",
        )

    @classmethod
    def _scientific(
        cls,
        *,
        spec_path,
        phase2a_inputs,
        dev_store_audit,
        response_artifact,
        sealed_outcome,
        activation_record,
        git_is_clean,
        environment,
        data_card_path,
        raw_asset_path,
        provenance_inputs,
    ) -> "RunSpecCarrier":
        return cls(
            spec_path=spec_path,
            phase2a_inputs=phase2a_inputs,
            dev_store_audit=dev_store_audit,
            response_artifact=response_artifact,
            sealed_outcome=sealed_outcome,
            mode="scientific",
            activation_record=activation_record,
            git_is_clean=git_is_clean,
            environment=environment,
            data_card_path=data_card_path,
            raw_asset_path=raw_asset_path,
            provenance_inputs=provenance_inputs,
        )


def load_run_spec_carrier(
    spec_path: str | Path,
    *,
    approved_artifacts_root: str | Path,
) -> RunSpecCarrier:
    """Reconstruct the stage-1 DATA carrier from a ResolvedRunSpec's on-disk artifacts.

    Peeks the declared ``mode`` (fixture is the only committed carrier path; a
    scientific spec fails closed with :class:`UnsupportedModeError`), loads and
    fully validates the immutable ResolvedRunSpec via
    :func:`~alive.compose.driver.run_spec.load_resolved_run_spec` (which SHA-
    verifies every pre-seal artifact against its on-disk bytes), then deserializes
    the four stage-1 objects the subcommands consume. Writes no new bytes and
    constructs no store.

    Parameters
    ----------
    spec_path : str or pathlib.Path
        Path to the canonical ResolvedRunSpec JSON.
    approved_artifacts_root : str or pathlib.Path
        The out-of-band CLI trust root; its canonical realpath must equal the
        spec's declared ``approved_artifacts_root``.

    Returns
    -------
    RunSpecCarrier
        The reconstructed carrier, duck-compatible with a ``FixtureBundle`` over
        the subcommand-consumed surface.

    Raises
    ------
    UnsupportedModeError
        If the declared ``mode`` is not ``"fixture"`` (scientific carriers are a
        PREPARE obligation, spec §0).
    RunSpecError
        If the ``mode`` cannot be peeked / is unrecognised, or the ResolvedRunSpec
        fails validation.
    """
    spec_path = Path(spec_path)
    mode = _peek_mode(spec_path)
    if mode != "fixture":
        raise UnsupportedModeError(
            "this loader can only reconstruct a run_spec carrier for mode='fixture' "
            "(scientific carrier assembly is a separate PREPARE obligation, spec §0); "
            f"got mode={mode!r}"
        )
    spec = load_resolved_run_spec(
        spec_path, approved_artifacts_root=approved_artifacts_root, mode_expected=mode
    )
    return RunSpecCarrier._fixture(
        spec_path=spec_path,
        phase2a_inputs=_load_phase2a_inputs(spec),
        dev_store_audit=_load_dev_store_audit(spec),
        response_artifact=_load_response_artifact(spec),
        sealed_outcome=_load_sealed_outcome(spec),
    )


# --------------------------------------------------------------------------- #
# mode peek + small helpers
# --------------------------------------------------------------------------- #


def _peek_mode(spec_path: Path) -> str:
    """Read the declared ``mode`` before the full load (loader re-validates it)."""
    try:
        raw = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RunSpecError(f"cannot read ResolvedRunSpec {spec_path}: {exc}") from exc
    mode = raw.get("mode") if isinstance(raw, dict) else None
    if mode not in _MODES:
        raise RunSpecError(f"ResolvedRunSpec declares an unrecognised mode {mode!r}")
    return mode


def _read_json(path: str | Path) -> dict[str, Any]:
    """Parse a pre-seal JSON stage-1 artifact (already SHA-verified by the loader)."""
    obj = json.loads(Path(path).read_bytes())
    if not isinstance(obj, dict):
        raise RunSpecError(f"stage-1 artifact {path} is not a JSON object")
    return obj


# --------------------------------------------------------------------------- #
# Bucket B — the four deserializers (readers of already-serialized data)
# --------------------------------------------------------------------------- #


def _load_phase2a_inputs(spec: ResolvedRunSpec) -> Phase2aInputs:
    """Rehydrate the live :class:`~alive.compose.phase2a.Phase2aInputs`.

    Inverse of ``fixture_builder._serialize_phase2a_inputs``: reconstructs every
    numpy array + grid + identity checksum and re-binds each serialized roster
    NAME to its learned-model factory via ``_MODEL_CLASS_BY_NAME`` (the single
    source of truth). ``content_checksum`` is recomputed in ``__post_init__`` and
    reproduces the serialized value because every field is byte-faithful.
    """
    payload = _read_json(spec.pre_seal["phase2a_inputs"].path)
    return Phase2aInputs(
        run_id=payload["run_id"],
        gene_index={str(g): int(i) for g, i in payload["gene_index"].items()},
        factors_by_k={
            int(k): np.asarray(v, dtype=np.float64) for k, v in payload["factors_by_k"].items()
        },
        cal_idx_pairs=[(int(a), int(b)) for a, b in payload["cal_idx_pairs"]],
        cal_pair_ids=[(str(a), str(b)) for a, b in payload["cal_pair_ids"]],
        additive_cal=np.asarray(payload["additive_cal"], dtype=np.float64),
        eps_split_a=np.asarray(payload["eps_split_a"], dtype=np.float64),
        eps_split_b=np.asarray(payload["eps_split_b"], dtype=np.float64),
        k_total_grid=[int(x) for x in payload["k_total_grid"]],
        lambda_grid=[float(x) for x in payload["lambda_grid"]],
        n_genes=int(payload["n_genes"]),
        n_folds=int(payload["n_folds"]),
        seed=int(payload["seed"]),
        uncovered_tolerance=float(payload["uncovered_tolerance"]),
        sealed_double_pair_ids=[(str(a), str(b)) for a, b in payload["sealed_double_pair_ids"]],
        sealed_single_pair_ids=[(str(a), str(b)) for a, b in payload["sealed_single_pair_ids"]],
        delta_by_gene={
            str(g): np.asarray(v, dtype=np.float64) for g, v in payload["delta_by_gene"].items()
        },
        model_factories={name: _MODEL_CLASS_BY_NAME[name] for name in payload["model_roster"]},
        response_dim=int(payload["response_dim"]),
        response_space_checksum=str(payload["response_space_checksum"]),
        factor_checksum=str(payload["factor_checksum"]),
        manifest_checksum=str(payload["manifest_checksum"]),
        environment_checksum=str(payload["environment_checksum"]),
        registered_seeds=[int(x) for x in payload["registered_seeds"]],
        data_card_checksum=str(payload["data_card_checksum"]),
        raw_data_checksum=str(payload["raw_data_checksum"]),
        sequence_mapping_checksum=str(payload["sequence_mapping_checksum"]),
    )


def _load_dev_store_audit(spec: ResolvedRunSpec) -> dict[str, Any]:
    """Rehydrate the non-sealed dev-store DATA (calibration eps + pair ids + audit).

    A phase2a subcommand builds the
    :class:`~alive.compose.phase2a.DevelopmentOutcomeStore` from these three keys;
    the :class:`~alive.compose.phase2a.OutcomeAccessAudit` is reconstructed from the
    manifest's ``access_audit`` block (its five fields map exactly).
    """
    source = _read_json(spec.pre_seal["development_outcome_source"].path)
    manifest = _read_json(spec.pre_seal["development_outcome_manifest"].path)
    return {
        "combo_calibration_eps": np.asarray(source["combo_calibration_eps"], dtype=np.float64),
        "combo_calibration_pair_ids": tuple(
            (str(a), str(b)) for a, b in source["combo_calibration_pair_ids"]
        ),
        "access_audit": OutcomeAccessAudit(**manifest["access_audit"]),
    }


def _load_response_artifact(spec: ResolvedRunSpec) -> dict[str, Any]:
    """Rehydrate the live response artifact (space + control_mean + fit-role spec)."""
    payload = _read_json(spec.pre_seal["response_artifact"].path)
    return {
        "response_space": _deserialize_response_space(payload["response_space"]),
        "control_mean": np.asarray(payload["control_mean"], dtype=np.float64),
        "combined_checksum": str(payload["combined_checksum"]),
        "gene_order": [str(g) for g in payload["gene_order"]],
        "raw_data_sha256": str(payload["raw_data_sha256"]),
        "fit_role_spec": _deserialize_fit_role_spec(payload["fit_role_artifact"]),
    }


def _deserialize_response_space(payload: Mapping[str, Any]) -> ResponseSpace:
    """Rebuild a live :class:`~alive.compose.response.ResponseSpace` from its payload.

    ``payload`` is ``json.loads(space.artifact_bytes())`` — the ROUNDED, checksum-
    excluding artifact payload. Its derived keys (``algorithm`` / ``version`` /
    ``transform`` / ``n_fit``) are not constructor fields and are ignored; the
    ``checksum`` is RECOMPUTED from the rehydrated space's ``artifact_bytes()``.
    Because rounding is idempotent, that reproduces the built space's checksum.
    """
    space = ResponseSpace(
        median_library=float(payload["median_library"]),
        hvg_idx=np.asarray(payload["hvg_idx"], dtype=np.intp),
        pca_components=np.asarray(payload["pca_components"], dtype=np.float64),
        pca_mean=np.asarray(payload["pca_mean"], dtype=np.float64),
        pca_explained_variance=np.asarray(payload["pca_explained_variance"], dtype=np.float64),
        n_hvg=int(payload["n_hvg"]),
        pca_dim=int(payload["pca_dim"]),
        seed=int(payload["seed"]),
        n_control=int(payload["n_control"]),
        n_eligible_single=int(payload["n_eligible_single"]),
        fit_index_hash=str(payload["fit_index_hash"]),
    )
    return dataclasses.replace(space, checksum=sha256_bytes(space.artifact_bytes()))


def _deserialize_fit_role_spec(block: Mapping[str, Any]) -> FitRoleArtifactSpec:
    """Rebuild the live :class:`~alive.compose.fit_role.FitRoleArtifactSpec`.

    Inverse of ``FitRoleArtifactSpec.to_payload_block``: maps the block back to the
    11 dataclass fields. The block's derived keys (``format`` /
    ``artifact_schema_version`` / ``role_obs_key`` / ``perturbation_obs_key`` /
    ``allowed_obs_roles`` / ``counts_location``) are not constructor fields and are
    ignored. Downstream reads ``.path`` / ``.sha256``, ``read_h5ad(.path)`` and
    ``.to_payload_block()``, so this must be a live object.
    """
    return FitRoleArtifactSpec(
        path=str(block["path"]),
        sha256=str(block["sha256"]),
        content_manifest_sha256=str(block["content_manifest_sha256"]),
        raw_data_sha256=str(block["raw_data_sha256"]),
        pair_manifest_sha256=str(block["pair_manifest_sha256"]),
        eligibility_hash=str(block["eligibility_hash"]),
        row_identity_sha256=str(block["row_identity_sha256"]),
        gene_order_sha256=str(block["gene_order_sha256"]),
        n_cells=int(block["n_cells"]),
        n_genes=int(block["n_genes"]),
        role_counts={str(k): int(v) for k, v in block["role_counts"].items()},
    )


def _load_sealed_outcome(spec: ResolvedRunSpec) -> dict[str, Any]:
    """Rehydrate the sealed-outcome DATA a ``phase2b`` subcommand builds its store FROM.

    Reads the split manifest + pair-index manifest (already SHA-verified) and
    reconstructs the ``pair_index`` (``{(gene_a, gene_b): row-index ndarray}``) from
    the manifest's ``pairs``. The sealed source path + expected digest come from the
    spec's ``fixture.sealed_input`` block; the corpus attestation triple from the
    committed ``FIXTURE_CORPUS_V1`` constant. NO outcome bytes are read (``phase2b``
    opens the source ``O_NOFOLLOW`` at seal time).
    """
    pair_index_manifest = _read_json(spec.pre_seal["pair_index_manifest"].path)
    split_manifest = _read_json(spec.pre_seal["pair_manifest"].path)
    pair_index = {
        (str(entry["gene_a"]), str(entry["gene_b"])): np.asarray(
            entry["row_indices"], dtype=np.int64
        )
        for entry in pair_index_manifest["pairs"]
    }
    sealed_input = spec.fixture["sealed_input"]
    return {
        "manifest": split_manifest,
        "pair_index": pair_index,
        "pair_index_manifest": pair_index_manifest,
        "source_path": Path(sealed_input["source_path"]),
        "source_file_sha256": str(sealed_input["expected_file_sha256"]),
        "perturbation_column": str(pair_index_manifest["perturbation_column"]),
        "combo_sep": str(pair_index_manifest["combo_sep"]),
        "corpus_id": FIXTURE_CORPUS_V1.corpus_id,
        "source_sha256": FIXTURE_CORPUS_V1.source_sha256,
        "builder_code_sha256": FIXTURE_CORPUS_V1.builder_code_sha256,
    }
