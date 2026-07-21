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

Scientific mode (spec §5, the "Scientific PREPARE carrier" sub-project). A scientific
ResolvedRunSpec requires an out-of-band ``trusted_repo_root`` (never selected by the
run spec) and, in assembly order: (1) loads + fully validates the spec, which also
validates the nested scientific block + pre-seal bytes; (2) validates the sealed-input
declaration against the owner attestation (lexical only — no source open); (3)
independently resolves the runtime Git/environment identity against the spec's
``approved_git_sha`` (fails closed on a moved HEAD or a dirty tree); (4) loads the
Phase-2 config and builds + re-validates the owner :class:`~alive.compose.config2.
ActivationRecord`; (5) reuses the fixture deserializers plus a scientific-only sealed-
outcome deserializer (:func:`_load_scientific_sealed_outcome`) that carries ONLY the
phase2b-consumed keys, never the fixture corpus attestation triple; (6) assembles typed
:class:`~alive.compose.phase2b.ActivationProvenanceInputs`; (7) constructs the carrier
via :meth:`RunSpecCarrier._scientific`. It opens no seal, constructs no
:class:`~alive.compose.outcome_store.ComposeOutcomeStore`, and opens no sealed AnnData
here — the sealed source stays lexical-only through step (2)'s validator.

See docs/superpowers/specs/2026-07-07-compose-production-driver-design.md §0/§1.1/§5/§11.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from alive.compose.approximation_bias import ApproximationBiasValidationError
from alive.compose.config2 import (
    ActivationRecord,
    ComposePhase2Config,
    assert_scientific_mode_allowed,
    load_compose_phase2_config,
)
from alive.compose.driver.bias_report_preseal import (
    ApproximationBiasDeclarationError,
    resolve_pinned_approximation_bias_evidence,
)
from alive.compose.driver.fixture_builder import _MODEL_CLASS_BY_NAME
from alive.compose.driver.pair_index import validate_scientific_sealed_declaration
from alive.compose.driver.run_spec import (
    ResolvedRunSpec,
    RunSpecError,
    load_resolved_run_spec,
)
from alive.compose.driver.scientific_runtime import resolve_scientific_runtime_context
from alive.compose.fit_role import FitRoleArtifactSpec
from alive.compose.outcome_store import FIXTURE_CORPUS_V1
from alive.compose.phase2a import OutcomeAccessAudit, Phase2aInputs
from alive.compose.phase2b import (
    ActivationProvenanceInputs,
    build_activation_provenance_inputs,
)
from alive.compose.response import ResponseSpace
from alive.provenance import EnvironmentInfo, sha256_bytes

__all__ = [
    "RunSpecCarrier",
    "UnsupportedModeError",
    "load_run_spec_carrier",
]

_MODES = frozenset({"fixture", "scientific"})


class UnsupportedModeError(RunSpecError):
    """Reserved for a future declared mode this loader has no way to build a carrier for.

    Subclasses :class:`~alive.compose.driver.run_spec.RunSpecError` so it would be
    caught by the CLI's SAME known-pre-seal-rejection mapping (exit ``10``) without a
    separate ``except`` clause. Both currently-recognised modes (``"fixture"`` and
    ``"scientific"``) now have a full carrier-assembly path in
    :func:`load_run_spec_carrier`; an unrecognised ``mode`` value fails closed earlier,
    in :func:`_peek_mode`, as a plain :class:`~alive.compose.driver.run_spec.RunSpecError`.
    This type is kept defined and exported for a future third mode.
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
        ``perturbation_column`` / ``combo_sep``, plus the corpus attestation triple in
        FIXTURE mode only — the scientific carrier omits it)
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
    trusted_repo_root: str | Path | None = None,
) -> RunSpecCarrier:
    """Reconstruct the stage-1 DATA carrier from a ResolvedRunSpec's on-disk artifacts.

    Fixture mode requires ``trusted_repo_root is None`` and reconstructs the five DATA fields.
    Scientific mode requires the out-of-band ``trusted_repo_root`` and, after loading + validating
    the spec, additionally validates the nested scientific block + sealed attestation, resolves the
    runtime git/environment identity against ``approved_git_sha``, builds + re-validates the owner
    ActivationRecord, assembles typed Phase-2b provenance, and constructs a scientific carrier via
    its scientific-only constructor. It opens no seal and constructs no store.

    Parameters
    ----------
    spec_path : str or pathlib.Path
        Path to the canonical ResolvedRunSpec JSON.
    approved_artifacts_root : str or pathlib.Path
        The out-of-band CLI trust root; its canonical realpath must equal the
        spec's declared ``approved_artifacts_root``.
    trusted_repo_root : str or pathlib.Path or None
        The out-of-band trusted repository root used ONLY in scientific mode to
        independently resolve the runtime Git/environment identity against the
        spec's ``approved_git_sha`` (never selected by the run spec itself).
        Fixture mode requires this to be ``None``; scientific mode requires it.

    Returns
    -------
    RunSpecCarrier
        The reconstructed carrier, duck-compatible with a ``FixtureBundle`` over
        the subcommand-consumed surface.

    Raises
    ------
    RunSpecError
        If the ``mode`` cannot be peeked / is unrecognised, if ``trusted_repo_root``
        is mismatched with the declared mode, if the ResolvedRunSpec fails
        validation, or if the sealed-input attestation equality check fails.
    alive.compose.driver.scientific_runtime.ScientificRuntimeError
        If the runtime Git/environment identity cannot be independently resolved
        against ``approved_git_sha`` (scientific mode only).
    alive.compose.config2.ScientificModeError
        If the assembled ActivationRecord is rejected by
        :func:`~alive.compose.config2.assert_scientific_mode_allowed` (scientific
        mode only).
    """
    spec_path = Path(spec_path)
    mode = _peek_mode(spec_path)
    if mode == "fixture":
        if trusted_repo_root is not None:
            raise RunSpecError(
                "fixture mode does not accept trusted_repo_root (disk-only carrier); pass None"
            )
        spec = load_resolved_run_spec(
            spec_path, approved_artifacts_root=approved_artifacts_root, mode_expected="fixture"
        )
        return RunSpecCarrier._fixture(
            spec_path=spec_path,
            phase2a_inputs=_load_phase2a_inputs(spec),
            dev_store_audit=_load_dev_store_audit(spec),
            response_artifact=_load_response_artifact(spec),
            sealed_outcome=_load_sealed_outcome(spec),
        )

    # scientific -----------------------------------------------------------
    if trusted_repo_root is None:
        raise RunSpecError(
            "scientific mode requires an out-of-band trusted_repo_root (never selected by the "
            "run spec); got None"
        )
    # §5.1: load + fully validate the spec (validates nested scientific schema + pre-seal bytes).
    spec = load_resolved_run_spec(
        spec_path, approved_artifacts_root=approved_artifacts_root, mode_expected="scientific"
    )
    # §5.2: sealed attestation equality (no source access).
    attestation = _read_json(spec.pre_seal["approved_sealed_input_attestation"].path)
    pair_index_manifest = _read_json(spec.pre_seal["pair_index_manifest"].path)
    validate_scientific_sealed_declaration(
        sealed_input=spec.scientific["sealed_input"],
        attestation=attestation,
        pair_index_manifest=pair_index_manifest,
        pair_index_manifest_file_sha256=spec.pre_seal["pair_index_manifest"].sha256,
        protocol=spec.protocol,
        approved_artifacts_root=spec.approved_artifacts_root,
    )
    # Load the config before runtime capture so EnvironmentInfo records the exact
    # pre-registered seed roster rather than an empty provenance placeholder.
    config = load_compose_phase2_config(spec.pre_seal["config"].path)
    _validate_scientific_approximation_bias_report(spec, config)
    # §5.3: runtime git/environment identity (fail closed vs approved_git_sha).
    context = resolve_scientific_runtime_context(
        trusted_repo_root=Path(trusted_repo_root),
        approved_git_sha=spec.approved_git_sha,
        lockfile_path=Path(spec.scientific["dependency_manifest"]["path"]),
        registered_seeds=config.registered_seeds,
    )
    # §5.4: config + ActivationRecord (re-validated through assert_scientific_mode_allowed).
    activation_record = _assemble_activation_record(spec, config, git_is_clean=context.git_is_clean)
    # §5.5-6: reuse deserializers + typed provenance.
    provenance_inputs = _assemble_provenance_inputs(spec, config, environment=context.environment)
    # §5.7: construct through the scientific-only constructor.
    return RunSpecCarrier._scientific(
        spec_path=spec_path,
        phase2a_inputs=_load_phase2a_inputs(spec),
        dev_store_audit=_load_dev_store_audit(spec),
        response_artifact=_load_response_artifact(spec),
        sealed_outcome=_load_scientific_sealed_outcome(spec),
        activation_record=activation_record,
        git_is_clean=context.git_is_clean,
        environment=context.environment,
        data_card_path=Path(spec.pre_seal["data_card"].path),
        raw_asset_path=Path(spec.pre_seal["raw_asset"].path),
        provenance_inputs=provenance_inputs,
    )


def _validate_scientific_approximation_bias_report(
    spec: ResolvedRunSpec, config: ComposePhase2Config
) -> None:
    """Bind the scientific report declaration to config and validate it pre-seal."""
    if spec.scientific is None:  # pragma: no cover - loader proves the mode block
        raise RunSpecError("scientific run spec has no scientific block")
    try:
        response = _load_response_artifact(spec)
        resolve_pinned_approximation_bias_evidence(spec, config, response_artifact=response)
    except ApproximationBiasDeclarationError as exc:
        raise RunSpecError(str(exc)) from exc
    except (OSError, ApproximationBiasValidationError) as exc:
        raise RunSpecError(
            f"scientific approximation-bias report failed pre-seal validation: {exc}"
        ) from exc


# --------------------------------------------------------------------------- #
# scientific-mode activation-record assembly (spec §2.1 / §5 step 4)
# --------------------------------------------------------------------------- #


def _assemble_activation_record(
    spec: ResolvedRunSpec, config: ComposePhase2Config, *, git_is_clean: bool
) -> ActivationRecord:
    """Build + re-validate the owner :class:`ActivationRecord` from the scientific block.

    ``owner`` is sourced from ``spec.scientific["activation_evidence"]["owner"]``;
    ``approved_protocol`` / ``approved_phase`` from the loaded ``config`` (NOT
    from the spec, which carries no protocol/phase field of its own);
    ``evidence_hashes`` / ``evidence_files`` from the exact requirement roster.
    :func:`~alive.compose.driver.run_spec.load_resolved_run_spec` (Task 2) already
    byte-SHA-verified every roster file against its declared digest, but it is
    config-unaware and cannot check the roster against
    ``config.activation_requirements`` — that exactness check happens here, and
    the assembled record is then re-validated through the real
    :func:`~alive.compose.config2.assert_scientific_mode_allowed` guard, which
    independently re-checks status/blockers/owner/protocol/phase/roster/
    digest-syntax/evidence-bytes/config-bound-report-lineage before scientific
    execution is allowed.

    Parameters
    ----------
    spec : alive.compose.driver.run_spec.ResolvedRunSpec
        The already-validated scientific ResolvedRunSpec.
    config : alive.compose.config2.ComposePhase2Config
        The loaded, validated Phase-2 config the spec's ``config`` field points at.
    git_is_clean : bool
        Whether the repository working tree is clean and committed; forwarded to
        the guard unchanged (this function performs no Git I/O itself).

    Returns
    -------
    alive.compose.config2.ActivationRecord
        The assembled, guard-validated owner activation record.

    Raises
    ------
    alive.compose.driver.run_spec.RunSpecError
        If the scientific block's requirement roster does not equal
        ``config.activation_requirements`` exactly.
    alive.compose.config2.ScientificModeError
        If :func:`~alive.compose.config2.assert_scientific_mode_allowed` rejects
        the assembled record (e.g. non-clean Git state, stale config-bound
        evidence, an unresolved activation blocker, or a digest/byte mismatch).
    """
    evidence = spec.scientific["activation_evidence"]
    requirements = evidence["requirements"]
    expected = set(config.activation_requirements)
    if set(requirements) != expected:
        raise RunSpecError(
            "activation_evidence.requirements must equal config.activation_requirements exactly: "
            f"missing={sorted(expected - set(requirements))} "
            f"extra={sorted(set(requirements) - expected)}"
        )
    record = ActivationRecord(
        owner=evidence["owner"],
        approved_protocol=config.protocol,
        approved_phase=config.phase,
        approved_git_sha=spec.approved_git_sha,
        approved_sequence_mapping_sha256=spec.sequence_mapping_digest,
        evidence_hashes={
            req: requirements[req]["sha256"] for req in config.activation_requirements
        },
        evidence_files={req: requirements[req]["path"] for req in config.activation_requirements},
    )
    assert_scientific_mode_allowed(config, activation_record=record, git_is_clean=git_is_clean)
    return record


# --------------------------------------------------------------------------- #
# scientific-mode provenance assembly (spec §4)
# --------------------------------------------------------------------------- #


def _processed_asset_path(spec: ResolvedRunSpec) -> str:
    """Return raw_asset.path ONLY if the validated data card declares it the processed asset (§4).

    The final PREPARE schema must add a separately verified ``processed_asset`` field if the raw
    asset is genuinely raw; until then this refuses to record a raw-file digest as
    ``processed_sha256`` unless the data card binds the raw asset AS the processed analysis asset.
    """
    raw = spec.pre_seal["raw_asset"]
    card = _read_json(spec.pre_seal["data_card"].path)
    declared = card.get("processed_analysis_asset")
    if not isinstance(declared, dict) or declared.get("sha256") != raw.sha256:
        raise RunSpecError(
            "data card does not identify raw_asset as the processed analysis asset; refusing to "
            "record a raw-file digest as processed_sha256 (spec §4 requires a separate "
            "processed_asset field for a genuinely raw asset)"
        )
    return raw.path


def _assemble_provenance_inputs(
    spec: ResolvedRunSpec, config: ComposePhase2Config, *, environment: EnvironmentInfo
) -> ActivationProvenanceInputs:
    """Build the typed Phase-2b provenance via the existing helper (§4 authoritative-source map)."""
    scientific = spec.scientific
    return build_activation_provenance_inputs(
        processed_path=_processed_asset_path(spec),
        feature_bank_path=spec.pre_seal["feature_bank"].path,
        dependency_lock_path=scientific["dependency_manifest"]["path"],
        gears_requirements_path=spec.worker_blocks["gears"].requirements_lock.path,
        cpa_requirements_path=spec.worker_blocks["cpa"].requirements_lock.path,
        environment=environment,
        device=scientific["device"],
        precision=scientific["precision"],
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


def _load_scientific_sealed_outcome(spec: ResolvedRunSpec) -> dict[str, Any]:
    """Rehydrate the scientific sealed-outcome DATA ``phase2b`` builds its store FROM (§3).

    Carries only the fields ``_build_sealed_store`` consumes — split manifest, pair index,
    pair-index manifest, declared source path/SHA (from the scientific ``sealed_input``),
    perturbation column and combo separator. It NEVER carries the fixture corpus attestation
    triple. No outcome bytes are read (``phase2b`` opens the source ``O_NOFOLLOW`` at seal time).
    """
    pair_index_manifest = _read_json(spec.pre_seal["pair_index_manifest"].path)
    split_manifest = _read_json(spec.pre_seal["pair_manifest"].path)
    pair_index = {
        (str(entry["gene_a"]), str(entry["gene_b"])): np.asarray(
            entry["row_indices"], dtype=np.int64
        )
        for entry in pair_index_manifest["pairs"]
    }
    sealed_input = spec.scientific["sealed_input"]
    return {
        "manifest": split_manifest,
        "pair_index": pair_index,
        "pair_index_manifest": pair_index_manifest,
        "source_path": Path(sealed_input["source_path"]),
        "source_file_sha256": str(sealed_input["expected_file_sha256"]),
        "perturbation_column": str(pair_index_manifest["perturbation_column"]),
        "combo_sep": str(pair_index_manifest["combo_sep"]),
    }
